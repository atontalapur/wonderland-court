"""Read-only SQLite WAL reader and schema definition for the Courtroom track."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from wonderland_court.contracts import Event, MatchMode, ScenarioId, parse_event

from .aggregator import build_bundle_from_events
from .models import (
    CalibrationSummary,
    FailureClusterView,
    RemediationAdviceView,
    RetrialComparisonView,
    RunBundle,
    RunSummary,
)

COURT_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    targets_json TEXT NOT NULL,
    defenses_json TEXT NOT NULL,
    scenarios_json TEXT NOT NULL,
    rounds INTEGER NOT NULL,
    matches INTEGER NOT NULL DEFAULT 0,
    leaks INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    match_id TEXT,
    event_json TEXT NOT NULL,
    UNIQUE(run_id, seq),
    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);

CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    target TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    defense TEXT NOT NULL,
    scenario TEXT NOT NULL,
    attacker TEXT NOT NULL,
    mode TEXT NOT NULL,
    seed INTEGER NOT NULL,
    broken INTEGER NOT NULL DEFAULT 0,
    turns INTEGER NOT NULL DEFAULT 0,
    broken_on_turn INTEGER,
    breaking_family TEXT,
    spec_json TEXT NOT NULL,
    stakes_json TEXT NOT NULL,
    PRIMARY KEY (run_id, match_id),
    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS standings (
    run_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    defense TEXT NOT NULL,
    elo REAL NOT NULL,
    matches INTEGER NOT NULL,
    attack_success REAL NOT NULL,
    ci_low REAL NOT NULL,
    ci_high REAL NOT NULL,
    mean_turns_to_break REAL,
    utility REAL,
    PRIMARY KEY (run_id, round, defense),
    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS utility_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    defense TEXT NOT NULL,
    task_id TEXT NOT NULL,
    passed INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    details_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS judge_calibration (
    run_id TEXT PRIMARY KEY,
    total_exact_checked INTEGER NOT NULL,
    llm_evaluated INTEGER NOT NULL,
    agreement_count INTEGER NOT NULL,
    agreement_rate REAL NOT NULL,
    false_positives INTEGER NOT NULL,
    false_negatives INTEGER NOT NULL,
    details_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS remediation_advice (
    run_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL,
    clusters_json TEXT NOT NULL,
    recommended_defense TEXT NOT NULL,
    config_patch_yaml TEXT NOT NULL,
    rationale TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS retrial_comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    baseline_run_id TEXT NOT NULL,
    retrial_run_id TEXT NOT NULL,
    matched_seeds_json TEXT NOT NULL,
    baseline_asr REAL NOT NULL,
    retrial_asr REAL NOT NULL,
    asr_delta REAL NOT NULL,
    baseline_utility REAL,
    retrial_utility REAL,
    per_scenario_diff_json TEXT NOT NULL,
    UNIQUE(baseline_run_id, retrial_run_id),
    FOREIGN KEY(baseline_run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(retrial_run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


async def init_court_db_schema(db_path: Path) -> None:
    """Create the Court SQLite schema in WAL mode. For tests and standalone harnesses only."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(COURT_SCHEMA_SQL)
        await conn.commit()


async def _table_exists(conn: aiosqlite.Connection, table_name: str) -> bool:
    async with conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ) as cursor:
        row = await cursor.fetchone()
    return row is not None


class CourtReadDB:
    """Strictly read-only SQLite WAL reader for Courtroom API and SSE tailing."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @asynccontextmanager
    async def _open_ro(self) -> AsyncIterator[aiosqlite.Connection | None]:
        if not self.db_path.is_file():
            yield None
            return
        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        conn: aiosqlite.Connection | None = None
        try:
            conn = await aiosqlite.connect(uri, uri=True)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA query_only = ON;")
        except sqlite3.Error:
            if conn is not None:
                await conn.close()
            yield None
            return
        try:
            yield conn
        finally:
            await conn.close()

    async def is_ready(self) -> bool:
        """Return True if the SQLite DB exists and has core Courtroom tables initialized."""
        try:
            async with self._open_ro() as conn:
                if conn is None:
                    return False
                return await _table_exists(conn, "events") or await _table_exists(conn, "runs")
        except sqlite3.Error:
            return False

    async def list_runs(self) -> list[RunSummary]:
        """List available runs ordered newest-first."""
        try:
            async with self._open_ro() as conn:
                if conn is None:
                    return []
                summaries: list[RunSummary] = []
                seen_run_ids: set[str] = set()

                if await _table_exists(conn, "events"):
                    async with conn.execute(
                        """
                        SELECT run_id
                        FROM events
                        GROUP BY run_id
                        ORDER BY MAX(ts) DESC, MAX(id) DESC
                        """
                    ) as cur:
                        run_rows = await cur.fetchall()

                    for row in run_rows:
                        run_id = str(row["run_id"])
                        events = await self._fetch_all_events(conn, run_id)
                        if events:
                            bundle = build_bundle_from_events(events, source="sqlite")
                            summaries.append(bundle.summary)
                            seen_run_ids.add(run_id)

                if not summaries and await _table_exists(conn, "runs"):
                    async with conn.execute(
                        "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC"
                    ) as cur:
                        rows = await cur.fetchall()
                    for row in rows:
                        run_id = str(row["run_id"])
                        if run_id in seen_run_ids:
                            continue
                        status_val = str(row["status"])
                        status = "completed" if status_val == "completed" else "running"
                        summaries.append(
                            RunSummary(
                                run_id=run_id,
                                mode=MatchMode(str(row["mode"])),
                                targets=[str(x) for x in json.loads(str(row["targets_json"]))],
                                defenses=[str(x) for x in json.loads(str(row["defenses_json"]))],
                                scenarios=[
                                    ScenarioId(str(x))
                                    for x in json.loads(str(row["scenarios_json"]))
                                ],
                                rounds=int(row["rounds"]),
                                matches=int(row["matches"]),
                                leaks=int(row["leaks"]),
                                status=status,
                                source="sqlite",
                            )
                        )
                        seen_run_ids.add(run_id)

                return summaries
        except sqlite3.Error:
            return []

    async def get_latest_run_id(self) -> str | None:
        """Return the most recently active run_id, or None if no runs exist."""
        try:
            async with self._open_ro() as conn:
                if conn is None:
                    return None
                if await _table_exists(conn, "events"):
                    async with conn.execute(
                        """
                        SELECT run_id
                        FROM events
                        GROUP BY run_id
                        ORDER BY MAX(ts) DESC, MAX(id) DESC
                        LIMIT 1
                        """
                    ) as cur:
                        row = await cur.fetchone()
                        if row is not None:
                            return str(row["run_id"])
                if await _table_exists(conn, "runs"):
                    async with conn.execute(
                        "SELECT run_id FROM runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
                    ) as cur:
                        row = await cur.fetchone()
                        if row is not None:
                            return str(row["run_id"])
                return None
        except sqlite3.Error:
            return None

    async def get_events_after(
        self,
        run_id: str,
        after_seq: int = -1,
        limit: int = 500,
    ) -> list[Event]:
        """Return ordered events for `run_id` with `seq > after_seq`."""
        if limit <= 0:
            return []
        try:
            async with self._open_ro() as conn:
                if conn is None or not await _table_exists(conn, "events"):
                    return []
                async with conn.execute(
                    """
                    SELECT event_json
                    FROM events
                    WHERE run_id = ? AND seq > ?
                    ORDER BY seq ASC
                    LIMIT ?
                    """,
                    (run_id, after_seq, limit),
                ) as cur:
                    rows = await cur.fetchall()
                return [parse_event(str(row["event_json"])) for row in rows]
        except sqlite3.Error:
            return []

    async def get_calibration(self, run_id: str) -> CalibrationSummary | None:
        """Return Wave 2 Queen of Hearts calibration metrics for `run_id`, if present."""
        try:
            async with self._open_ro() as conn:
                if conn is None:
                    return None
                return await self._fetch_calibration(conn, run_id)
        except sqlite3.Error:
            return None

    async def get_advice(self, run_id: str) -> RemediationAdviceView | None:
        """Return Wave 2 Caterpillar remediation advice for `run_id`, if present."""
        try:
            async with self._open_ro() as conn:
                if conn is None:
                    return None
                return await self._fetch_advice(conn, run_id)
        except sqlite3.Error:
            return None

    async def get_retrial_diff(self, run_id: str) -> RetrialComparisonView | None:
        """Return Wave 2 before/after retrial comparison matching `run_id`, if present."""
        try:
            async with self._open_ro() as conn:
                if conn is None:
                    return None
                return await self._fetch_retrial_diff(conn, run_id)
        except sqlite3.Error:
            return None

    async def get_run_bundle(self, run_id: str) -> RunBundle | None:
        """Reconstruct a complete RunBundle for `run_id`, or None if not found."""
        try:
            async with self._open_ro() as conn:
                if conn is None or not await _table_exists(conn, "events"):
                    return None
                events = await self._fetch_all_events(conn, run_id)
                if not events:
                    return None
                calibration = await self._fetch_calibration(conn, run_id)
                advice = await self._fetch_advice(conn, run_id)
                retrial = await self._fetch_retrial_diff(conn, run_id)
                return build_bundle_from_events(
                    events,
                    source="sqlite",
                    calibration=calibration,
                    advice=advice,
                    retrial=retrial,
                )
        except sqlite3.Error:
            return None

    async def _fetch_all_events(self, conn: aiosqlite.Connection, run_id: str) -> list[Event]:
        async with conn.execute(
            """
            SELECT event_json
            FROM events
            WHERE run_id = ?
            ORDER BY seq ASC
            """,
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [parse_event(str(row["event_json"])) for row in rows]

    async def _fetch_calibration(
        self, conn: aiosqlite.Connection, run_id: str
    ) -> CalibrationSummary | None:
        if not await _table_exists(conn, "judge_calibration"):
            return None
        async with conn.execute(
            "SELECT * FROM judge_calibration WHERE run_id = ? LIMIT 1",
            (run_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        keys = set(row.keys())
        if "calibration_json" in keys and row["calibration_json"] is not None:
            return CalibrationSummary.model_validate_json(str(row["calibration_json"]))
        return CalibrationSummary(
            run_id=str(row["run_id"]),
            total_exact_checked=int(row["total_exact_checked"]),
            llm_evaluated=int(row["llm_evaluated"]),
            agreement_count=int(row["agreement_count"]),
            agreement_rate=float(row["agreement_rate"]),
            false_positives=int(row["false_positives"]),
            false_negatives=int(row["false_negatives"]),
        )

    async def _fetch_advice(
        self, conn: aiosqlite.Connection, run_id: str
    ) -> RemediationAdviceView | None:
        if not await _table_exists(conn, "remediation_advice"):
            return None
        async with conn.execute(
            "SELECT * FROM remediation_advice WHERE run_id = ? LIMIT 1",
            (run_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        keys = set(row.keys())
        if "advice_json" in keys and row["advice_json"] is not None:
            return RemediationAdviceView.model_validate_json(str(row["advice_json"]))
        raw_clusters: list[dict[str, Any]] = json.loads(str(row["clusters_json"]))
        clusters = [FailureClusterView.model_validate(item) for item in raw_clusters]
        return RemediationAdviceView(
            run_id=str(row["run_id"]),
            target_kind=str(row["target_kind"]),
            clusters=clusters,
            recommended_defense=str(row["recommended_defense"]),
            config_patch_yaml=str(row["config_patch_yaml"]),
            rationale=str(row["rationale"]),
        )

    async def _fetch_retrial_diff(
        self, conn: aiosqlite.Connection, run_id: str
    ) -> RetrialComparisonView | None:
        if not await _table_exists(conn, "retrial_comparisons"):
            return None
        async with conn.execute(
            """
            SELECT *
            FROM retrial_comparisons
            WHERE retrial_run_id = ? OR baseline_run_id = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (run_id, run_id),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        keys = set(row.keys())
        if "comparison_json" in keys and row["comparison_json"] is not None:
            return RetrialComparisonView.model_validate_json(str(row["comparison_json"]))
        matched_seeds = [int(s) for s in json.loads(str(row["matched_seeds_json"]))]
        per_scenario_diff: dict[str, dict[str, float]] = json.loads(
            str(row["per_scenario_diff_json"])
        )
        baseline_util = row["baseline_utility"]
        retrial_util = row["retrial_utility"]
        return RetrialComparisonView(
            baseline_run_id=str(row["baseline_run_id"]),
            retrial_run_id=str(row["retrial_run_id"]),
            matched_seeds=matched_seeds,
            baseline_asr=float(row["baseline_asr"]),
            retrial_asr=float(row["retrial_asr"]),
            asr_delta=float(row["asr_delta"]),
            baseline_utility=float(baseline_util) if baseline_util is not None else None,
            retrial_utility=float(retrial_util) if retrial_util is not None else None,
            per_scenario_diff=per_scenario_diff,
        )
