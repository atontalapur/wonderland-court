"""Splitting one tournament across laptops, and joining the parts back up.

`court trial --shard k/N` plays the k-th of every N matches in the schedule (`idx % N == k - 1`),
and the k-th of every N Dodo checks. The schedule, match ids and seeds are the same on every
laptop, so the N parts never overlap and together cover the whole tournament.

`court merge` reads the latest finished run from each database (or the runs named with
`--run`), checks they are parts of one tournament, and writes one run to `--out`: every match
and its events, renumbered from 0 with times that never go backwards, the Dodo's results, and
the standings for every round recomputed over all the matches. The merged leaderboard is the
one an unsharded run of the same tournament would have produced.
"""

import contextlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self, TypeVar

from wonderland_court.config import parse_shard
from wonderland_court.contracts import (
    AttackSent,
    Event,
    MatchEnded,
    MatchSpec,
    MatchStarted,
    ReplyReceived,
    RunEnded,
    RunStarted,
    Standing,
    StandingsUpdated,
    VerdictRuled,
)

from .runner import EventLog, new_run_id
from .scoring import compute_standings
from .store import CourtReader, CourtStore, MatchRecord, RunRecord, UtilityResult

T = TypeVar("T")

PER_LAPTOP = frozenset({"shard", "db_path", "match_timeout_s"})
"""Settings that may differ between the parts of one tournament."""
MATCH_EVENTS = (MatchStarted, AttackSent, ReplyReceived, VerdictRuled, MatchEnded)


@dataclass(frozen=True)
class Shard:
    """Part `part` of `total`, counting from 1."""

    part: int
    total: int

    def __post_init__(self) -> None:
        if not 1 <= self.part <= self.total:
            raise ValueError(f"shard {self} should be k/N with 1 <= k <= N")

    @classmethod
    def parse(cls, spec: str) -> Self:
        return cls(*parse_shard(spec))

    def __str__(self) -> str:
        return f"{self.part}/{self.total}"

    def owns(self, index: int) -> bool:
        return index % self.total == self.part - 1

    def select(self, items: Sequence[T]) -> list[T]:
        """The items this part plays, in their original order."""
        return [item for index, item in enumerate(items) if self.owns(index)]


# court merge


class MergeError(ValueError):
    """The runs can't be merged into one tournament."""


@dataclass(frozen=True)
class MergePart:
    """One run to merge, as read from its database."""

    db: Path
    run: RunRecord
    events: list[Event]
    matches: list[MatchRecord]
    utility: list[UtilityResult]

    @property
    def shard(self) -> Shard | None:
        spec = self.run.config.get("shard")
        return Shard.parse(spec) if spec else None

    @property
    def started(self) -> RunStarted:
        for event in self.events:
            if isinstance(event, RunStarted):
                return event
        raise MergeError(f"run {self.run.run_id} in {self.db} has no run_started event")

    def __str__(self) -> str:
        shard = f", shard {self.shard}" if self.shard else ""
        return f"run {self.run.run_id} in {self.db}{shard}"


@dataclass(frozen=True)
class MergeResult:
    run_id: str
    out: Path
    parts: list[MergePart]
    matches: int
    leaks: int
    standings: list[Standing]
    missing: list[str]
    """Shards that weren't merged, as `k/N`. Only a `partial` merge leaves any out."""


async def read_parts(dbs: Sequence[Path], run_ids: Sequence[str] = ()) -> list[MergePart]:
    """The latest finished run from each database, or the runs named in `run_ids`."""
    wanted = set(run_ids)
    parts: list[MergePart] = []
    for db in dbs:
        async with CourtReader(db) as reader:
            runs = await reader.list_runs()
            if wanted:
                chosen = [run for run in runs if run.run_id in wanted]
                if not chosen:
                    raise MergeError(f"none of the runs given with --run are in {db}")
            else:
                chosen = [run for run in runs if run.status == "finished"][:1]
                if not chosen:
                    raise MergeError(f"{db} has no finished run")
            for run in chosen:
                if run.status != "finished":
                    raise MergeError(f"run {run.run_id} in {db} is {run.status}, not finished")
                parts.append(
                    MergePart(
                        db,
                        run,
                        await reader.get_events_after(run.run_id),
                        await reader.get_matches(run.run_id),
                        await reader.get_utility_results(run.run_id),
                    )
                )
    seen = Counter(part.run.run_id for part in parts)
    if twice := sorted(run_id for run_id, count in seen.items() if count > 1):
        raise MergeError(f"run {', '.join(twice)} was given more than once")
    if missing := sorted(wanted - seen.keys()):
        raise MergeError(f"no run {', '.join(missing)} in {', '.join(map(str, dbs))}")
    return parts


def check_parts(parts: Sequence[MergePart], *, partial: bool = False) -> list[str]:
    """Raise `MergeError` unless the parts are disjoint pieces of one tournament. Returns the
    shards that are missing, which is an error too unless `partial` is set."""
    if not parts:
        raise MergeError("nothing to merge")
    first = parts[0]
    for part in parts[1:]:
        keys = (first.run.config.keys() | part.run.config.keys()) - PER_LAPTOP
        differ = sorted(
            key for key in keys if first.run.config.get(key) != part.run.config.get(key)
        )
        if differ or (part.run.target, part.run.target_kind) != (
            first.run.target,
            first.run.target_kind,
        ):
            what = ", ".join(differ) or "target"
            raise MergeError(f"{part} has a different {what} from {first}")
        a, b = first.started, part.started
        if (a.targets, a.defenses, a.scenarios, a.mode, a.rounds) != (
            b.targets,
            b.defenses,
            b.scenarios,
            b.mode,
            b.rounds,
        ):
            raise MergeError(f"{part} played different defenses or scenarios from {first}")

    setups = {
        (
            tuple(spec.enabled_families or ()),
            tuple(spec.enabled_mutators or ()),
            spec.attacker,
            spec.max_turns,
        )
        for part in parts
        for spec in (e.match for e in part.events if isinstance(e, MatchStarted))
    }
    if len(setups) > 1:
        raise MergeError("the runs used different attackers, --family or --mutator flags")

    # Shards first: two parts of different splits also overlap, and this says why.
    split = [part.shard for part in parts if part.shard is not None]
    sharded = len(split) == len(parts)
    if sharded:
        if len({shard.total for shard in split}) > 1:
            shown = ", ".join(map(str, split))
            raise MergeError(f"the shards come from different splits: {shown}")
        have = Counter(shard.part for shard in split)
        if twice := [f"{part}/{split[0].total}" for part, count in have.items() if count > 1]:
            raise MergeError(f"shard {', '.join(twice)} was given more than once")

    played = Counter(
        event.match.match_id
        for part in parts
        for event in part.events
        if isinstance(event, MatchStarted)
    )
    if overlap := sorted(match_id for match_id, count in played.items() if count > 1):
        shown = ", ".join(overlap[:5]) + (", ..." if len(overlap) > 5 else "")
        raise MergeError(f"the runs overlap: {len(overlap)} matches appear twice ({shown})")

    if not sharded:
        return []  # an unsharded run is complete on its own, and the overlap check covers it
    total = split[0].total
    missing = [f"{part}/{total}" for part in range(1, total + 1) if part not in have]
    if missing and not partial:
        names = ", ".join(missing)
        which = f"shard {names} is" if len(missing) == 1 else f"shards {names} are"
        raise MergeError(f"{which} missing; merge them too, or pass --partial")
    return missing


async def merge_runs(
    dbs: Sequence[Path],
    out: Path,
    *,
    run_ids: Sequence[str] = (),
    partial: bool = False,
    run_id: str | None = None,
) -> MergeResult:
    """Merge the parts of one tournament from `dbs` into one finished run in `out`.

    `out` may be one of `dbs`: every part is read before anything is written. Its JSONL copy
    goes to `runs/` next to `out`, as `court trial` does.
    """
    parts = await read_parts(dbs, run_ids)
    missing = check_parts(parts, partial=partial)
    parts.sort(key=lambda part: (part.shard.part if part.shard else 0, part.run.run_id))
    first = parts[0]
    started = first.started
    run_id = run_id or new_run_id()

    records = [replace(match, run_id=run_id) for part in parts for match in part.matches]
    scored = {record.match_id for record in records}
    utility = [replace(result, run_id=run_id) for part in parts for result in part.utility]
    keys = Counter((result.defense, result.scenario) for result in utility)
    if twice := [f"{d} in {s.value}" for (d, s), count in keys.items() if count > 1]:
        raise MergeError(f"the Dodo scored {', '.join(twice)} in more than one run")

    timeline = _timeline(parts)
    rounds = sorted(
        {round for round, *_ in timeline}
        | {e.round for part in parts for e in part.events if isinstance(e, StandingsUpdated)}
    )
    now = [min(part.started.ts for part in parts)]
    config = {**first.run.config, "shard": None, "db_path": str(out)}

    async with CourtStore(out, jsonl_dir=out.parent / "runs") as store:
        events = EventLog(run_id, store.append_event, clock=lambda: now[0])
        await store.create_run(
            RunRecord(
                run_id=run_id,
                mode=first.run.mode,
                target=first.run.target,
                target_kind=first.run.target_kind,
                config=config,
            )
        )
        try:
            await events.emit(
                RunStarted,
                targets=started.targets,
                defenses=started.defenses,
                scenarios=started.scenarios,
                mode=started.mode,
                rounds=started.rounds,
            )
            specs: dict[str, MatchSpec] = {}
            standings = compute_standings([], defenses=started.defenses)
            for round in rounds:
                for _, ts, _, _, event in (step for step in timeline if step[0] == round):
                    now[0] = ts
                    copied = await events.emit(type(event), **_fields(event))
                    if isinstance(copied, MatchStarted):
                        specs[copied.match.match_id] = copied.match
                    elif isinstance(copied, MatchEnded) and copied.match_id in scored:
                        await store.save_match_result(specs[copied.match_id], copied)
                upto = [record for record in records if record.round <= round]
                standings = compute_standings(upto, defenses=started.defenses)
                await publish_standings(store, events, round, standings)

            if utility and rounds:
                for result in utility:
                    await store.save_utility_result(result)
                table = {(result.defense, result.scenario): result.pass_rate for result in utility}
                standings = compute_standings(records, defenses=started.defenses, utility=table)
                await publish_standings(store, events, rounds[-1], standings)

            leaks = sum(record.broken for record in records)
            await events.emit(RunEnded, matches=len(records), leaks=leaks)
        except BaseException:
            with contextlib.suppress(Exception):
                await store.set_run_status(run_id, "failed")
            raise
        await store.set_run_status(run_id, "finished")

    return MergeResult(run_id, out, parts, len(records), leaks, standings, missing)


def _timeline(parts: Sequence[MergePart]) -> list[tuple[int, datetime, int, int, Event]]:
    """Every match event from every part as (round, ts, part, seq, event), in merge order: by
    round, then time, then part, then the part's own order."""
    steps: list[tuple[int, datetime, int, int, Event]] = []
    for index, part in enumerate(parts):
        rounds = {
            e.match.match_id: e.match.round for e in part.events if isinstance(e, MatchStarted)
        }
        for event in part.events:
            if isinstance(event, MATCH_EVENTS):
                match_id = (
                    event.match.match_id if isinstance(event, MatchStarted) else event.match_id
                )
                steps.append((rounds[match_id], event.ts.astimezone(UTC), index, event.seq, event))
    steps.sort(key=lambda step: step[:4])
    return steps


def _fields(event: Event) -> dict[str, Any]:
    """An event's own fields, without the envelope the merged log writes afresh."""
    envelope = {"v", "seq", "ts", "run_id", "type"}
    return {name: getattr(event, name) for name in type(event).model_fields if name not in envelope}


async def publish_standings(
    store: CourtStore, events: EventLog, round: int, standings: list[Standing]
) -> None:
    """Save a round's board and announce it, so the table and the live stream agree. The
    tournament does this after each round, and the merge after each merged round."""
    await store.upsert_standings(events.run_id, round, standings)
    await events.emit(StandingsUpdated, round=round, standings=standings)
