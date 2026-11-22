"""The White Rabbit's ledger: one SQLite file in WAL mode.

`CourtStore` owns the only write connection. Every write goes through one writer task, in the
order it was submitted, and the caller awaits its result or its error. Reads use a separate
read-only connection. `CourtReader` opens the same read-only view on its own, so `court serve`
can tail a live run from another process without ever writing.

With `jsonl_dir` set, every event also lands in `<jsonl_dir>/<run_id>.jsonl` as the exact
`dump_event` line, so each run can be replayed from a plain file.
"""

import asyncio
import contextlib
import json
import sqlite3
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self, TextIO, TypeVar

import aiosqlite

from ..contracts import (
    Event,
    MatchEnded,
    MatchMode,
    MatchSpec,
    ScenarioId,
    Standing,
    TargetKind,
    TargetReply,
    dump_event,
    parse_event,
)

BUSY_TIMEOUT_MS: Final = 5000

T = TypeVar("T")
_Job = Callable[[aiosqlite.Connection], Awaitable[T]]


# Rows that have no contract model


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    mode: MatchMode
    target: str
    target_kind: TargetKind
    config: dict[str, Any] = field(default_factory=dict)
    parent_run_id: str | None = None
    """The run this one retries, for Caterpillar re-runs."""
    status: str = "running"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class MatchRecord:
    """A finished match: its `MatchSpec` joined with its `MatchEnded` result."""

    match_id: str
    run_id: str
    round: int
    target: str
    target_kind: TargetKind
    defense: str
    scenario: ScenarioId
    mode: MatchMode
    family: str | None
    seed: int
    broken: bool
    turns: int
    broken_on_turn: int | None
    breaking_family: str | None

    @classmethod
    def from_result(cls, spec: MatchSpec, result: MatchEnded) -> Self:
        if spec.match_id != result.match_id:
            raise ValueError(f"spec is {spec.match_id!r} but result is {result.match_id!r}")
        return cls(
            match_id=spec.match_id,
            run_id=result.run_id,
            round=spec.round,
            target=spec.target,
            target_kind=spec.target_kind,
            defense=spec.defense,
            scenario=spec.scenario,
            mode=spec.mode,
            family=spec.family,
            seed=spec.seed,
            broken=result.broken,
            turns=result.turns,
            broken_on_turn=result.broken_on_turn,
            breaking_family=result.breaking_family,
        )


@dataclass(frozen=True, slots=True)
class UtilityResult:
    """The Dodo's benign-task score for one defense in one scenario."""

    run_id: str
    defense: str
    scenario: ScenarioId
    pass_rate: float
    false_refusal_rate: float | None
    """None when the evaluator only reports a pass rate, as the registry's does."""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JudgeCalibration:
    """How often the LLM judge agreed with the exact checks over one run."""

    run_id: str
    total_exact_checked: int
    llm_evaluated: int
    agreement_count: int
    agreement_rate: float
    false_positives: int
    false_negatives: int


@dataclass(frozen=True, slots=True)
class RemediationAdvice:
    """Advice from a Caterpillar for one run."""

    run_id: str
    target_kind: TargetKind
    clusters: list[dict[str, Any]]
    recommended_defense: str
    config_patch_yaml: str
    rationale: str


@dataclass(frozen=True, slots=True)
class RetrialComparison:
    """A re-run on the hardened config against its baseline, on matched seeds."""

    retrial_run_id: str
    baseline_run_id: str
    matched_seeds: list[int]
    baseline_asr: float
    retrial_asr: float
    asr_delta: float
    baseline_utility: float | None
    retrial_utility: float | None
    per_scenario: dict[str, Any]


class CourtReader:
    """Read-only view of a court database. Safe to open while another process writes to it."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._read_db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        if not self.db_path.exists():
            raise FileNotFoundError(f"no court database at {self.db_path}")
        db = await aiosqlite.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
        db.row_factory = aiosqlite.Row
        await db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        self._read_db = db

    async def close(self) -> None:
        if self._read_db is not None:
            db, self._read_db = self._read_db, None
            await db.close()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def list_runs(self) -> list[RunRecord]:
        """Every run, newest first."""
        rows = await self._rows("SELECT * FROM runs ORDER BY created_at DESC, run_id DESC")
        return [_run_record(row) for row in rows]

    async def get_run(self, run_id: str) -> RunRecord | None:
        row = await self._row("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        return None if row is None else _run_record(row)

    async def get_events_after(self, run_id: str, after_seq: int = -1) -> list[Event]:
        """Events with `seq > after_seq`, in order. A tailer passes the last seq it saw."""
        rows = await self._rows(
            "SELECT event_json FROM events WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, after_seq),
        )
        return [parse_event(row["event_json"]) for row in rows]

    async def get_matches(self, run_id: str) -> list[MatchRecord]:
        rows = await self._rows(
            "SELECT * FROM matches WHERE run_id = ? ORDER BY round, match_id", (run_id,)
        )
        return [
            MatchRecord(
                match_id=row["match_id"],
                run_id=row["run_id"],
                round=row["round"],
                target=row["target"],
                target_kind=TargetKind(row["target_kind"]),
                defense=row["defense"],
                scenario=ScenarioId(row["scenario"]),
                mode=MatchMode(row["mode"]),
                family=row["family"],
                seed=row["seed"],
                broken=bool(row["broken"]),
                turns=row["turns"],
                broken_on_turn=row["broken_on_turn"],
                breaking_family=row["breaking_family"],
            )
            for row in rows
        ]

    async def get_latest_standings(self, run_id: str) -> list[Standing]:
        """The leaderboard from the run's highest round, best Elo first."""
        rows = await self._rows(
            """
            SELECT * FROM standings
            WHERE run_id = ? AND round = (SELECT MAX(round) FROM standings WHERE run_id = ?)
            ORDER BY elo DESC, defense
            """,
            (run_id, run_id),
        )
        return [
            Standing.model_validate({name: row[name] for name in Standing.model_fields})
            for row in rows
        ]

    async def get_utility_results(self, run_id: str) -> list[UtilityResult]:
        rows = await self._rows(
            "SELECT * FROM utility_results WHERE run_id = ? ORDER BY defense, scenario", (run_id,)
        )
        return [
            UtilityResult(
                run_id=row["run_id"],
                defense=row["defense"],
                scenario=ScenarioId(row["scenario"]),
                pass_rate=row["pass_rate"],
                false_refusal_rate=row["false_refusal_rate"],
                details=json.loads(row["details_json"]),
            )
            for row in rows
        ]

    async def get_calibration(self, run_id: str) -> JudgeCalibration | None:
        row = await self._row("SELECT * FROM judge_calibration WHERE run_id = ?", (run_id,))
        return None if row is None else JudgeCalibration(**dict(row))

    async def get_advice(self, run_id: str) -> RemediationAdvice | None:
        row = await self._row("SELECT * FROM remediation_advice WHERE run_id = ?", (run_id,))
        if row is None:
            return None
        return RemediationAdvice(
            run_id=row["run_id"],
            target_kind=TargetKind(row["target_kind"]),
            clusters=json.loads(row["clusters_json"]),
            recommended_defense=row["recommended_defense"],
            config_patch_yaml=row["config_patch_yaml"],
            rationale=row["rationale"],
        )

    async def get_retrial_comparison(self, retrial_run_id: str) -> RetrialComparison | None:
        row = await self._row(
            "SELECT * FROM retrial_comparisons WHERE retrial_run_id = ?", (retrial_run_id,)
        )
        if row is None:
            return None
        return RetrialComparison(
            retrial_run_id=row["retrial_run_id"],
            baseline_run_id=row["baseline_run_id"],
            matched_seeds=json.loads(row["matched_seeds_json"]),
            baseline_asr=row["baseline_asr"],
            retrial_asr=row["retrial_asr"],
            asr_delta=row["asr_delta"],
            baseline_utility=row["baseline_utility"],
            retrial_utility=row["retrial_utility"],
            per_scenario=json.loads(row["per_scenario_json"]),
        )

    async def cache_get(self, key: str) -> TargetReply | None:
        row = await self._row("SELECT reply_json FROM llm_cache WHERE cache_key = ?", (key,))
        return None if row is None else TargetReply.model_validate_json(row["reply_json"])

    async def _rows(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        if self._read_db is None:
            raise RuntimeError(f"{type(self).__name__} is not started")
        return list(await self._read_db.execute_fetchall(sql, params))

    async def _row(self, sql: str, params: Sequence[Any]) -> sqlite3.Row | None:
        rows = await self._rows(sql, params)
        return rows[0] if rows else None


class CourtStore(CourtReader):
    """The read-write store. Open one per database; it holds the only write connection."""

    def __init__(self, db_path: Path, jsonl_dir: Path | None = None) -> None:
        super().__init__(db_path)
        self.jsonl_dir = jsonl_dir
        self._write_db: aiosqlite.Connection | None = None
        self._queue: asyncio.Queue[tuple[_Job[Any], asyncio.Future[Any]] | None] = asyncio.Queue()
        self._writer: asyncio.Task[None] | None = None
        self._accepting = False
        self._sinks: dict[Path, TextIO] = {}

    async def start(self) -> None:
        """Open the database, apply `schema.sql`, switch to WAL and start the writer task."""
        if self._write_db is not None:
            raise RuntimeError("CourtStore is already started")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.jsonl_dir is not None:
            self.jsonl_dir.mkdir(parents=True, exist_ok=True)
        self._write_db = db = await aiosqlite.connect(self.db_path)
        try:
            await db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            await db.executescript(_schema())
            await db.execute("PRAGMA synchronous=NORMAL")
            [(journal_mode,)] = await db.execute_fetchall("PRAGMA journal_mode")
            if journal_mode != "wal":
                raise RuntimeError(f"{self.db_path} cannot use WAL (journal_mode={journal_mode})")
            self._queue = asyncio.Queue()
            self._writer = asyncio.create_task(self._writer_loop(db), name="court-store-writer")
            self._accepting = True
            await super().start()
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        """Finish every queued write, then close. Calling it twice is fine."""
        self._accepting = False
        try:
            if self._writer is not None:
                self._queue.put_nowait(None)
                await self._writer
        finally:
            self._writer = None
            for sink in self._sinks.values():
                sink.close()
            self._sinks.clear()
            if self._write_db is not None:
                db, self._write_db = self._write_db, None
                await db.close()
            await super().close()

    # Writers. Each one waits until its write is committed, or raises the write's error.

    async def create_run(self, run: RunRecord) -> None:
        await self._insert(
            "runs",
            {
                "run_id": run.run_id,
                "parent_run_id": run.parent_run_id,
                "created_at": run.created_at.astimezone(UTC).isoformat(),
                "mode": run.mode.value,
                "target": run.target,
                "target_kind": run.target_kind.value,
                "config_json": json.dumps(run.config, sort_keys=True),
                "status": run.status,
            },
        )

    async def set_run_status(self, run_id: str, status: str) -> None:
        async def job(db: aiosqlite.Connection) -> None:
            cursor = await db.execute(
                "UPDATE runs SET status = ? WHERE run_id = ?", (status, run_id)
            )
            if cursor.rowcount == 0:
                raise KeyError(run_id)

        await self._write(job)

    async def append_event(self, event: Event) -> None:
        """Record one event, and with a JSONL sink, append the same line to the run's file."""
        line = dump_event(event)
        path = self._jsonl_path(event.run_id)

        async def job(db: aiosqlite.Connection) -> None:
            await db.execute(
                "INSERT INTO events (seq, run_id, ts, type, event_json) VALUES (?, ?, ?, ?, ?)",
                (event.seq, event.run_id, event.ts.isoformat(), event.type, line),
            )
            if path is not None:
                await db.commit()  # first, so the file never holds a line the database lacks
                sink = self._sinks.get(path)
                if sink is None:
                    sink = self._sinks[path] = path.open("a", encoding="utf-8", newline="\n")
                sink.write(line + "\n")
                sink.flush()

        await self._write(job)

    async def save_match_result(self, spec: MatchSpec, result: MatchEnded) -> None:
        record = MatchRecord.from_result(spec, result)
        await self._insert(
            "matches",
            {
                **asdict(record),
                "target_kind": record.target_kind.value,
                "scenario": record.scenario.value,
                "mode": record.mode.value,
                "broken": int(record.broken),
            },
        )

    async def upsert_standings(
        self, run_id: str, round: int, standings: Sequence[Standing]
    ) -> None:
        rows = [{"run_id": run_id, "round": round, **s.model_dump()} for s in standings]
        await self._insert_many("standings", rows, replace=True)

    async def save_utility_result(self, result: UtilityResult) -> None:
        await self._insert(
            "utility_results",
            {
                "run_id": result.run_id,
                "defense": result.defense,
                "scenario": result.scenario.value,
                "pass_rate": result.pass_rate,
                "false_refusal_rate": result.false_refusal_rate,
                "details_json": json.dumps(result.details, sort_keys=True),
            },
            replace=True,
        )

    async def save_judge_calibration(self, calibration: JudgeCalibration) -> None:
        await self._insert("judge_calibration", asdict(calibration), replace=True)

    async def save_remediation_advice(self, advice: RemediationAdvice) -> None:
        await self._insert(
            "remediation_advice",
            {
                "run_id": advice.run_id,
                "target_kind": advice.target_kind.value,
                "clusters_json": json.dumps(advice.clusters, sort_keys=True),
                "recommended_defense": advice.recommended_defense,
                "config_patch_yaml": advice.config_patch_yaml,
                "rationale": advice.rationale,
            },
            replace=True,
        )

    async def save_retrial_comparison(self, comparison: RetrialComparison) -> None:
        await self._insert(
            "retrial_comparisons",
            {
                "retrial_run_id": comparison.retrial_run_id,
                "baseline_run_id": comparison.baseline_run_id,
                "matched_seeds_json": json.dumps(comparison.matched_seeds),
                "baseline_asr": comparison.baseline_asr,
                "retrial_asr": comparison.retrial_asr,
                "asr_delta": comparison.asr_delta,
                "baseline_utility": comparison.baseline_utility,
                "retrial_utility": comparison.retrial_utility,
                "per_scenario_json": json.dumps(comparison.per_scenario, sort_keys=True),
            },
            replace=True,
        )

    async def cache_put(self, key: str, reply: TargetReply) -> None:
        await self._insert(
            "llm_cache",
            {
                "cache_key": key,
                "reply_json": reply.model_dump_json(),
                "created_at": datetime.now(UTC).isoformat(),
            },
            replace=True,
        )

    # The single writer

    async def _write(self, job: _Job[T]) -> T:
        if not self._accepting:
            raise RuntimeError("CourtStore is closed or not started")
        future: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        self._queue.put_nowait((job, future))
        return await future

    async def _writer_loop(self, db: aiosqlite.Connection) -> None:
        while (item := await self._queue.get()) is not None:
            job, future = item
            if future.cancelled():  # the caller gave up before its turn came
                continue
            try:
                result = await job(db)
                await db.commit()
            except Exception as exc:
                # The caller gets the original error; a failed rollback must not hide it.
                with contextlib.suppress(Exception):
                    await db.rollback()
                if not future.done():
                    future.set_exception(exc)
            else:
                if not future.done():
                    future.set_result(result)

    async def _insert(self, table: str, row: Mapping[str, Any], *, replace: bool = False) -> None:
        await self._insert_many(table, [row], replace=replace)

    async def _insert_many(
        self, table: str, rows: Sequence[Mapping[str, Any]], *, replace: bool
    ) -> None:
        if not rows:
            return
        columns = list(rows[0])
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        sql = (
            f"{verb} INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join(f':{column}' for column in columns)})"
        )

        async def job(db: aiosqlite.Connection) -> None:
            await db.executemany(sql, rows)

        await self._write(job)

    def _jsonl_path(self, run_id: str) -> Path | None:
        if self.jsonl_dir is None:
            return None
        name = f"{run_id}.jsonl"
        if Path(name).name != name:
            raise ValueError(f"run_id {run_id!r} cannot be used as a file name")
        return self.jsonl_dir / name


def _schema() -> str:
    return (
        resources.files("wonderland_court.engine")
        .joinpath("schema.sql")
        .read_text(encoding="utf-8")
    )


def _run_record(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        mode=MatchMode(row["mode"]),
        target=row["target"],
        target_kind=TargetKind(row["target_kind"]),
        config=json.loads(row["config_json"]),
        parent_run_id=row["parent_run_id"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
