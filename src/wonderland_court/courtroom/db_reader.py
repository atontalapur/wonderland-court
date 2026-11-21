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

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "engine" / "schema.sql"
COURT_SCHEMA_SQL = _SCHEMA_PATH.read_text(encoding="utf-8")


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


async def _table_columns(conn: aiosqlite.Connection, table_name: str) -> set[str]:
    async with conn.execute(f'PRAGMA table_info("{table_name}")') as cur:
        rows = await cur.fetchall()
    return {str(row[1]) for row in rows}


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
                        ORDER BY MAX(ts) DESC, MAX(seq) DESC
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
                    run_cols = await _table_columns(conn, "runs")
                    order_col = (
                        "created_at"
                        if "created_at" in run_cols
                        else ("started_at" if "started_at" in run_cols else "rowid")
                    )
                    async with conn.execute(
                        f"SELECT * FROM runs ORDER BY {order_col} DESC, rowid DESC"
                    ) as cur:
                        rows = await cur.fetchall()
                    for row in rows:
                        run_id = str(row["run_id"])
                        if run_id in seen_run_ids:
                            continue
                        keys = set(row.keys())
                        cfg: dict[str, Any] = (
                            json.loads(str(row["config_json"]))
                            if "config_json" in keys and row["config_json"]
                            else {}
                        )
                        targets = (
                            [str(x) for x in json.loads(str(row["targets_json"]))]
                            if "targets_json" in keys and row["targets_json"]
                            else (
                                [str(row["target"])] if "target" in keys and row["target"] else []
                            )
                        )
                        defenses = (
                            [str(x) for x in json.loads(str(row["defenses_json"]))]
                            if "defenses_json" in keys and row["defenses_json"]
                            else [str(x) for x in cfg.get("defenses", [])]
                        )
                        scenarios = (
                            [ScenarioId(str(x)) for x in json.loads(str(row["scenarios_json"]))]
                            if "scenarios_json" in keys and row["scenarios_json"]
                            else [ScenarioId(str(x)) for x in cfg.get("scenarios", [])]
                        )
                        status_val = (
                            str(row["status"]) if "status" in keys and row["status"] else "running"
                        )
                        status = "completed" if status_val == "completed" else "running"
                        summaries.append(
                            RunSummary(
                                run_id=run_id,
                                mode=MatchMode(str(row["mode"] or "adaptive")),
                                targets=targets,
                                defenses=defenses,
                                scenarios=scenarios,
                                rounds=int(row["rounds"])
                                if "rounds" in keys and row["rounds"]
                                else 1,
                                matches=int(row["matches"])
                                if "matches" in keys and row["matches"]
                                else 0,
                                leaks=int(row["leaks"]) if "leaks" in keys and row["leaks"] else 0,
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
                        ORDER BY MAX(ts) DESC, MAX(seq) DESC
                        LIMIT 1
                        """
                    ) as cur:
                        row = await cur.fetchone()
                        if row is not None:
                            return str(row["run_id"])
                if await _table_exists(conn, "runs"):
                    run_cols = await _table_columns(conn, "runs")
                    order_col = (
                        "created_at"
                        if "created_at" in run_cols
                        else ("started_at" if "started_at" in run_cols else "rowid")
                    )
                    async with conn.execute(
                        f"SELECT run_id FROM runs ORDER BY {order_col} DESC, rowid DESC LIMIT 1"
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
        raw_per_scen = (
            row["per_scenario_json"]
            if "per_scenario_json" in keys
            else row["per_scenario_diff_json"]
        )
        per_scenario_diff: dict[str, dict[str, float]] = json.loads(str(raw_per_scen or "{}"))
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
