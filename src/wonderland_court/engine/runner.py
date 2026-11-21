"""The White Rabbit: plays matches, runs the trial, and writes every event.

A match is one defense stack against one scenario. Each turn the Cat attacks, the defended
Alice replies, and the Queen rules. The first leak ends the match ("Off with her head!").

Every defense in a round faces the same scenario seed, so the same canary and the same
attacks: a difference in outcome comes from the defense, not from luck. `court retrial`
replays those seeds against a hardened config.
"""

import asyncio
import contextlib
import hashlib
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from wonderland_court.config import CourtConfig
from wonderland_court.contracts import (
    AttackContext,
    Attacker,
    AttackSent,
    Event,
    Judge,
    MatchEnded,
    MatchMode,
    MatchSpec,
    MatchStarted,
    Message,
    MutatorId,
    ReplyReceived,
    Ruling,
    RunEnded,
    RunStarted,
    ScenarioId,
    Stakes,
    Target,
    TargetKind,
    TechniqueFamily,
    Turn,
    VerdictRuled,
)
from wonderland_court.contracts.events import EventBase

from .defenses import DefensePolicy, compose_defenses
from .scenarios import build_scenario
from .store import CourtStore, RunRecord

E = TypeVar("E", bound=EventBase)
Sink = Callable[[Event], Awaitable[None]]


def _now() -> datetime:
    return datetime.now(UTC)


class EventLog:
    """Numbers one run's events and hands them to a sink, one at a time.

    `seq` counts up from 0 and `ts` never goes backwards, even with matches running at once.
    An event the sink rejects doesn't use up its `seq`.
    """

    def __init__(self, run_id: str, sink: Sink, clock: Callable[[], datetime] = _now) -> None:
        self.run_id = run_id
        self._sink = sink
        self._clock = clock
        self._seq = 0
        self._last: datetime | None = None
        self._lock = asyncio.Lock()

    async def emit(self, kind: type[E], **fields: Any) -> E:
        async with self._lock:
            ts = self._clock()
            if self._last is not None and ts < self._last:
                ts = self._last
            event = kind(seq=self._seq, ts=ts, run_id=self.run_id, **fields)
            await self._sink(cast(Event, event))
            self._seq += 1
            self._last = ts
            return event


@dataclass(frozen=True)
class MatchResult:
    spec: MatchSpec
    stakes: Stakes
    ended: MatchEnded
    turns: list[Turn]


async def run_match(
    spec: MatchSpec, target: Target, attacker: Attacker, judge: Judge, log: EventLog
) -> MatchResult:
    """Play one match and emit `match_started`, `(attack, reply, verdict)` per turn, then
    `match_ended`. The defense stack comes from `spec.defense`.

    The attacker sees the objective and the conversation, never the canary.
    """
    scenario = build_scenario(spec.scenario, spec.seed)
    stakes = scenario.stakes
    policy = DefensePolicy(tool_rules=tuple(stakes.tool_rules))
    defended = compose_defenses(spec.defense, target, policy)
    await log.emit(MatchStarted, match=spec, stakes=stakes)

    turns: list[Turn] = []
    conversation: list[Message] = []
    for index in range(1, spec.max_turns + 1):
        context = AttackContext(
            match_id=spec.match_id,
            scenario=spec.scenario,
            objective=stakes.objective,
            mode=spec.mode,
            family=spec.family,
            enabled_families=spec.enabled_families,
            enabled_mutators=spec.enabled_mutators,
            turn=index,
            history=list(turns),
        )
        attack = await attacker.next_attack(context)
        await log.emit(AttackSent, match_id=spec.match_id, turn=index, attack=attack)

        messages = [*conversation, Message(role="user", content=attack.message)]
        documents = [attack.document] if attack.document else None
        reply = await defended.respond(scenario.request(messages, documents))
        await log.emit(ReplyReceived, match_id=spec.match_id, turn=index, reply=reply)

        verdict = await judge.rule(stakes, attack, reply)
        await log.emit(VerdictRuled, match_id=spec.match_id, turn=index, verdict=verdict)

        turns.append(Turn(index=index, attack=attack, reply=reply, verdict=verdict))
        conversation = [*messages, Message(role="assistant", content=reply.content)]
        if verdict.ruling is Ruling.LEAK:
            ended = await log.emit(
                MatchEnded,
                match_id=spec.match_id,
                broken=True,
                turns=index,
                broken_on_turn=index,
                breaking_family=attack.family,
            )
            return MatchResult(spec, stakes, ended, turns)

    ended = await log.emit(MatchEnded, match_id=spec.match_id, broken=False, turns=len(turns))
    return MatchResult(spec, stakes, ended, turns)


# The trial


def match_seed(base: int, round: int, scenario: ScenarioId) -> int:
    """The scenario seed for one round. Every defense in the round shares it."""
    digest = hashlib.sha256(f"wonderland-court:{base}:{round}:{scenario.value}".encode()).digest()
    return int.from_bytes(digest[:4], "big") >> 1


def plan_matches(
    config: CourtConfig,
    *,
    target: str,
    target_kind: TargetKind,
    attacker: str,
    defenses: Sequence[str],
    families: Sequence[TechniqueFamily] = (),
    mutators: Sequence[MutatorId] = (),
) -> list[MatchSpec]:
    """Every match of the trial: rounds × scenarios × defenses, and × families in fixed mode.

    Match ids count up from `m001` in that order, so they are unique within the run.
    """
    if config.mode is MatchMode.FIXED and not families:
        raise ValueError("fixed mode needs at least one technique family (--family)")
    assigned: list[str | None] = (
        [family.value for family in families] if config.mode is MatchMode.FIXED else [None]
    )
    specs: list[MatchSpec] = []
    for round in range(1, config.rounds + 1):
        for scenario in config.scenarios:
            seed = match_seed(config.seed, round, scenario)
            for defense in defenses:
                for family in assigned:
                    specs.append(
                        MatchSpec(
                            match_id=f"m{len(specs) + 1:03d}",
                            round=round,
                            target=target,
                            target_kind=target_kind,
                            defense=defense,
                            scenario=scenario,
                            attacker=attacker,
                            mode=config.mode,
                            family=family,
                            enabled_families=list(families) or None,
                            enabled_mutators=list(mutators) or None,
                            max_turns=config.max_turns,
                            seed=seed,
                        )
                    )
    return specs


def new_run_id() -> str:
    return f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


@dataclass(frozen=True)
class TrialResult:
    run_id: str
    matches: list[MatchResult]

    @property
    def leaks(self) -> int:
        return sum(match.ended.broken for match in self.matches)


async def run_trial(
    config: CourtConfig,
    *,
    target: Target,
    attacker: Attacker,
    judge: Judge,
    store: CourtStore,
    defenses: Sequence[str] | None = None,
    families: Sequence[TechniqueFamily] = (),
    mutators: Sequence[MutatorId] = (),
    run_id: str | None = None,
    concurrency: int = 2,
    on_event: Callable[[Event], None] | None = None,
    clock: Callable[[], datetime] = _now,
) -> TrialResult:
    """Run every planned match, `concurrency` at a time, and record the run in the store.

    `defenses` defaults to the config's. The LLM client enforces the real rate limits; the
    concurrency bound only keeps the event stream readable. The run's status ends as
    `finished`, or `failed` if anything raised; the first match error is re-raised as is.
    """
    defenses = list(config.defenses if defenses is None else defenses)
    specs = plan_matches(
        config,
        target=target.name,
        target_kind=target.kind,
        attacker=attacker.name,
        defenses=defenses,
        families=families,
        mutators=mutators,
    )
    run_id = run_id or new_run_id()

    async def sink(event: Event) -> None:
        await store.append_event(event)
        if on_event is not None:
            on_event(event)

    log = EventLog(run_id, sink, clock)
    await store.create_run(
        RunRecord(
            run_id=run_id,
            mode=config.mode,
            target=target.name,
            target_kind=target.kind,
            config=config.model_dump(mode="json"),
        )
    )
    gate = asyncio.Semaphore(concurrency)

    async def play(spec: MatchSpec) -> MatchResult:
        async with gate:
            result = await run_match(spec, target, attacker, judge, log)
            await store.save_match_result(spec, result.ended)
            return result

    try:
        await log.emit(
            RunStarted,
            targets=[target.name],
            defenses=defenses,
            scenarios=list(config.scenarios),
            mode=config.mode,
            rounds=config.rounds,
        )
        try:
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(play(spec)) for spec in specs]
        except ExceptionGroup as errors:  # the first failure cancels the rest
            raise errors.exceptions[0] from errors
        results = [task.result() for task in tasks]
        await log.emit(RunEnded, matches=len(results), leaks=sum(r.ended.broken for r in results))
    except BaseException:
        with contextlib.suppress(Exception):
            await store.set_run_status(run_id, "failed")
        raise
    await store.set_run_status(run_id, "finished")
    return TrialResult(run_id, results)
