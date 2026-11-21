"""Tests for Courtroom server, SQLite WAL reader, SSE tailing, and rate limiting."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import httpx
import pytest
import uvicorn

from wonderland_court.contracts import Event, RunStarted, dump_event, parse_event, read_events
from wonderland_court.courtroom.db_reader import CourtReadDB, init_court_db_schema
from wonderland_court.courtroom.server import create_app

ROOT = Path(__file__).resolve().parents[2]
FAKE_RUN = ROOT / "fixtures" / "fake_run.jsonl"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        assert isinstance(port, int)
        return port


@contextlib.asynccontextmanager
async def _running_server(
    db_path: Path,
    *,
    max_requests_per_min: int = 120,
    max_sse_per_ip: int = 3,
) -> AsyncIterator[str]:
    port = _free_port()
    app = create_app(
        db_path=db_path,
        max_requests_per_min=max_requests_per_min,
        max_sse_per_ip=max_sse_per_ip,
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    base_url = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient(base_url=base_url) as probe:
            for _ in range(50):
                try:
                    resp = await probe.get("/health-probe-static")
                    if resp.status_code == 200:
                        break
                except httpx.ConnectError:
                    await asyncio.sleep(0.05)
        yield base_url
    finally:
        server.should_exit = True
        await task


async def _seed_run_events(db_path: Path, events: list[Event]) -> None:
    run_started = next(ev for ev in events if isinstance(ev, RunStarted))
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, parent_run_id, created_at, mode, target, target_kind, config_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_started.run_id,
                None,
                run_started.ts.isoformat(),
                run_started.mode.value,
                run_started.targets[0] if run_started.targets else "ollama:llama3.1",
                "model",
                json.dumps(
                    {
                        "targets": run_started.targets,
                        "defenses": run_started.defenses,
                        "scenarios": [s.value for s in run_started.scenarios],
                        "rounds": run_started.rounds,
                    }
                ),
                "running",
            ),
        )
        for ev in events:
            await conn.execute(
                """
                INSERT INTO events (seq, run_id, ts, type, event_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ev.seq,
                    ev.run_id,
                    ev.ts.isoformat(),
                    ev.type,
                    dump_event(ev),
                ),
            )
        await conn.commit()


async def _seed_wave2_tables(db_path: Path, run_id: str) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute(
            """
            INSERT INTO runs (
                run_id, parent_run_id, created_at, mode, target, target_kind, config_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "retrial-run-0002",
                run_id,
                "2026-11-21T11:00:00Z",
                "adaptive",
                "ollama:llama3.1",
                "model",
                json.dumps(
                    {
                        "defenses": ["spotlighting+guard+output_filter"],
                        "scenarios": ["refund_tool", "vault"],
                    }
                ),
                "completed",
            ),
        )
        await conn.execute(
            """
            INSERT INTO judge_calibration (
                run_id, total_exact_checked, llm_evaluated, agreement_count,
                agreement_rate, false_positives, false_negatives
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, 8, 5, 5, 1.0, 0, 0),
        )
        await conn.execute(
            """
            INSERT INTO remediation_advice (
                run_id, target_kind, clusters_json, recommended_defense,
                config_patch_yaml, rationale
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "model",
                json.dumps(
                    [
                        {
                            "cluster_id": "cluster-1",
                            "family_label": "Indirect Prompt Injection",
                            "technique_family": "indirect_injection",
                            "scenario": "refund_tool",
                            "count": 1,
                            "example_match_ids": ["m01"],
                            "root_cause_summary": "Model followed hidden instructions in email.",
                        }
                    ]
                ),
                "spotlighting+guard+output_filter",
                "defense: spotlighting+guard+output_filter\n",
                "Blocks indirect injection and checks tool arguments.",
            ),
        )
        await conn.execute(
            """
            INSERT INTO retrial_comparisons (
                retrial_run_id, baseline_run_id, matched_seeds_json,
                baseline_asr, retrial_asr, asr_delta,
                baseline_utility, retrial_utility, per_scenario_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "retrial-run-0002",
                run_id,
                json.dumps([2751, 504]),
                0.375,
                0.0,
                -0.375,
                0.96,
                0.95,
                json.dumps({"refund_tool": {"baseline_asr": 0.25, "retrial_asr": 0.0}}),
            ),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_missing_db_graceful_startup(tmp_path: Path) -> None:
    missing_db = tmp_path / "does_not_exist.db"
    app = create_app(db_path=missing_db, static_dir=tmp_path / "missing_static")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "mode": "live",
            "db_ready": False,
            "replay_speed": 4.0,
        }

        runs = await client.get("/api/runs")
        assert runs.status_code == 200
        assert runs.json() == {"runs": []}

        bundle = await client.get("/api/runs/fake-run-0001/bundle")
        assert bundle.status_code == 404

        cal = await client.get("/api/runs/fake-run-0001/calibration")
        assert cal.status_code == 200
        assert cal.json() is None

        adv = await client.get("/api/runs/fake-run-0001/advice")
        assert adv.status_code == 200
        assert adv.json() is None

        diff = await client.get("/api/runs/fake-run-0001/retrial-diff")
        assert diff.status_code == 200
        assert diff.json() is None

        spa = await client.get("/")
        assert spa.status_code == 200
        assert "Wonderland Court" in spa.text

    assert not missing_db.exists()


@pytest.mark.asyncio
async def test_seeded_wal_db_rest_endpoints_and_static_spa(tmp_path: Path) -> None:
    db_path = tmp_path / "court.db"
    await init_court_db_schema(db_path)

    events = list(read_events(FAKE_RUN))
    await _seed_run_events(db_path, events)
    await _seed_wave2_tables(db_path, "fake-run-0001")

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html><body>SPA OK</body></html>", encoding="utf-8")
    (static_dir / "assets" / "app.js").write_text("console.log('ok');", encoding="utf-8")

    app = create_app(db_path=db_path, static_dir=static_dir)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["db_ready"] is True
        assert health.json()["mode"] == "live"

        runs = await client.get("/api/runs")
        assert runs.status_code == 200
        run_ids = [r["run_id"] for r in runs.json()["runs"]]
        assert "fake-run-0001" in run_ids

        bundle = await client.get("/api/runs/fake-run-0001/bundle")
        assert bundle.status_code == 200
        bjson = bundle.json()
        assert bjson["summary"]["source"] == "sqlite"
        assert bjson["summary"]["matches"] == 8
        assert bjson["summary"]["leaks"] == 3
        assert bjson["calibration"]["agreement_rate"] == 1.0
        assert bjson["advice"]["recommended_defense"] == "spotlighting+guard+output_filter"
        assert bjson["retrial"]["asr_delta"] == -0.375

        ev_resp = await client.get("/api/runs/fake-run-0001/events?after_seq=75")
        assert ev_resp.status_code == 200
        assert [e["seq"] for e in ev_resp.json()["events"]] == [76, 77, 78]

        standings = await client.get("/api/runs/fake-run-0001/standings")
        assert standings.status_code == 200
        assert standings.json()["run_id"] == "fake-run-0001"
        assert len(standings.json()["standings"]) == 4

        heatmap = await client.get("/api/runs/fake-run-0001/heatmap")
        assert heatmap.status_code == 200
        assert heatmap.json()["run_id"] == "fake-run-0001"
        assert len(heatmap.json()["cells"]) > 0

        cal = await client.get("/api/runs/fake-run-0001/calibration")
        assert cal.status_code == 200
        assert cal.json()["total_exact_checked"] == 8

        adv = await client.get("/api/runs/fake-run-0001/advice")
        assert adv.status_code == 200
        assert adv.json()["clusters"][0]["cluster_id"] == "cluster-1"

        diff = await client.get("/api/runs/fake-run-0001/retrial-diff")
        assert diff.status_code == 200
        assert diff.json()["retrial_run_id"] == "retrial-run-0002"

        # SPA static assets and client-side fallback
        asset = await client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "console.log('ok')" in asset.text

        fallback = await client.get("/matches/m01")
        assert fallback.status_code == 200
        assert "SPA OK" in fallback.text

        unknown_api = await client.get("/api/does-not-exist")
        assert unknown_api.status_code == 404


@pytest.mark.asyncio
async def test_read_db_cannot_mutate_database(tmp_path: Path) -> None:
    db_path = tmp_path / "court.db"
    await init_court_db_schema(db_path)
    reader = CourtReadDB(db_path)
    async with reader._open_ro() as conn:
        assert conn is not None
        with pytest.raises(sqlite3.OperationalError):
            await conn.execute("CREATE TABLE should_fail (id INTEGER)")


@pytest.mark.asyncio
async def test_api_rate_limit_121st_request_returns_429(tmp_path: Path) -> None:
    app = create_app(db_path=tmp_path / "missing.db", max_requests_per_min=120)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for idx in range(120):
            resp = await client.get("/api/health")
            assert resp.status_code == 200, f"request {idx + 1} failed unexpectedly"

        blocked = await client.get("/api/runs")
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
        assert int(blocked.headers["Retry-After"]) >= 1

        # Static non-API routes remain accessible
        spa = await client.get("/")
        assert spa.status_code == 200


@pytest.mark.asyncio
async def test_live_sse_incremental_tailing_and_last_event_id(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    await init_court_db_schema(db_path)
    events = list(read_events(FAKE_RUN))
    await _seed_run_events(db_path, events[:3])

    async with (
        _running_server(db_path) as base_url,
        httpx.AsyncClient(base_url=base_url, timeout=10.0) as client,
    ):
        received_seqs: list[int] = []
        async with client.stream("GET", "/api/runs/fake-run-0001/stream") as stream_resp:
            assert stream_resp.status_code == 200
            lines_iter = stream_resp.aiter_lines()
            writer_triggered = False

            async for line in lines_iter:
                if line.startswith("data: "):
                    ev = parse_event(line[6:])
                    received_seqs.append(ev.seq)
                    if received_seqs == [0, 1, 2] and not writer_triggered:
                        writer_triggered = True
                        # Concurrently append seq 3 to WAL DB while SSE stream is open
                        async with aiosqlite.connect(db_path) as conn:
                            ev3 = events[3]
                            await conn.execute(
                                """
                                INSERT INTO events (seq, run_id, ts, type, event_json)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    ev3.seq,
                                    ev3.run_id,
                                    ev3.ts.isoformat(),
                                    ev3.type,
                                    dump_event(ev3),
                                ),
                            )
                            await conn.commit()
                    if len(received_seqs) == 4:
                        break

        assert received_seqs == [0, 1, 2, 3]

        # Verify Last-Event-ID reconnect resumes from seq > 1
        resumed_seqs: list[int] = []
        async with client.stream(
            "GET",
            "/api/stream/latest",
            headers={"Last-Event-ID": "1"},
        ) as resumed_resp:
            assert resumed_resp.status_code == 200
            async for line in resumed_resp.aiter_lines():
                if line.startswith("data: "):
                    resumed_seqs.append(parse_event(line[6:]).seq)
                    if len(resumed_seqs) == 2:
                        break
        assert resumed_seqs == [2, 3]


@pytest.mark.asyncio
async def test_sse_concurrent_ip_limit_and_recovery(tmp_path: Path) -> None:
    db_path = tmp_path / "sse_limit.db"
    await init_court_db_schema(db_path)
    events = list(read_events(FAKE_RUN))
    await _seed_run_events(db_path, events[:2])

    async with (
        _running_server(db_path, max_sse_per_ip=3) as base_url,
        httpx.AsyncClient(base_url=base_url, timeout=10.0) as client,
    ):
        cm1 = client.stream("GET", "/api/runs/fake-run-0001/stream")
        cm2 = client.stream("GET", "/api/runs/fake-run-0001/stream")
        cm3 = client.stream("GET", "/api/runs/fake-run-0001/stream")

        s1 = await cm1.__aenter__()
        s2 = await cm2.__aenter__()
        s3 = await cm3.__aenter__()
        it1 = s1.aiter_lines()
        it2 = s2.aiter_lines()
        it3 = s3.aiter_lines()
        try:
            for stream, it in ((s1, it1), (s2, it2), (s3, it3)):
                assert stream.status_code == 200
                # Consume until first data line while keeping iterator and socket alive
                while True:
                    line = await anext(it)
                    if line.startswith("data: "):
                        break

            # 4th simultaneous SSE stream from same IP must return 429
            fourth = await client.get("/api/runs/fake-run-0001/stream")
            assert fourth.status_code == 429
            assert "Retry-After" in fourth.headers
        finally:
            await cm1.__aexit__(None, None, None)
            if (aclose := getattr(it1, "aclose", None)) is not None:
                await aclose()

        # Give uvicorn/Starlette a brief tick to run disconnect cleanup
        recovered = False
        for _ in range(20):
            async with client.stream("GET", "/api/runs/fake-run-0001/stream") as s4:
                if s4.status_code == 200:
                    recovered = True
                    break
            await asyncio.sleep(0.05)

        try:
            assert recovered, "SSE slot was not released after closing an active stream"
        finally:
            await cm2.__aexit__(None, None, None)
            await cm3.__aexit__(None, None, None)
            for it in (it2, it3):
                if (aclose := getattr(it, "aclose", None)) is not None:
                    await aclose()


@pytest.mark.asyncio
async def test_spa_fallback_blocks_path_traversal(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<html><body>INDEX_SAFE</body></html>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("TOP_SECRET_DO_NOT_LEAK", encoding="utf-8")

    app = create_app(db_path=tmp_path / "missing.db", static_dir=static_dir)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for attack_path in ("/../secret.txt", "/../../pyproject.toml", "/%2e%2e/secret.txt"):
            res = await client.get(attack_path)
            assert res.status_code == 200
            assert "TOP_SECRET_DO_NOT_LEAK" not in res.text
            assert "INDEX_SAFE" in res.text


@pytest.mark.asyncio
async def test_nullable_wave2_columns_do_not_500(tmp_path: Path) -> None:
    db_path = tmp_path / "nullable_wave2.db"
    await init_court_db_schema(db_path)
    events = list(read_events(FAKE_RUN))
    await _seed_run_events(db_path, events)

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("INSERT INTO judge_calibration (run_id) VALUES (?)", ("fake-run-0001",))
        await conn.execute("INSERT INTO remediation_advice (run_id) VALUES (?)", ("fake-run-0001",))
        await conn.execute(
            "INSERT INTO retrial_comparisons (retrial_run_id, baseline_run_id) VALUES (?, ?)",
            ("retrial-null-0002", "fake-run-0001"),
        )
        await conn.commit()

    app = create_app(db_path=db_path, static_dir=tmp_path / "no_static")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for ep in ("bundle", "calibration", "advice", "retrial-diff"):
            resp = await client.get(f"/api/runs/fake-run-0001/{ep}")
            assert resp.status_code == 200, f"{ep} failed: {resp.text}"


@pytest.mark.asyncio
async def test_engine_court_store_interop_with_server_and_reports(tmp_path: Path) -> None:
    from wonderland_court.contracts import MatchMode, TargetKind
    from wonderland_court.courtroom.reports import write_report
    from wonderland_court.engine.store import (
        CourtStore,
        JudgeCalibration,
        RemediationAdvice,
        RetrialComparison,
        RunRecord,
    )

    db_path = tmp_path / "engine_interop.db"
    events = list(read_events(FAKE_RUN))
    run_started = events[0]
    assert isinstance(run_started, RunStarted)

    async with CourtStore(db_path) as store:
        await store.create_run(
            RunRecord(
                run_id=run_started.run_id,
                mode=MatchMode(run_started.mode),
                target=run_started.targets[0],
                target_kind=TargetKind.MODEL,
                config={"defenses": run_started.defenses},
                status="completed",
            )
        )
        for ev in events:
            await store.append_event(ev)
        await store.save_judge_calibration(
            JudgeCalibration(
                run_id=run_started.run_id,
                total_exact_checked=8,
                llm_evaluated=5,
                agreement_count=5,
                agreement_rate=1.0,
                false_positives=0,
                false_negatives=0,
            )
        )
        await store.save_remediation_advice(
            RemediationAdvice(
                run_id=run_started.run_id,
                target_kind=TargetKind.MODEL,
                clusters=[
                    {
                        "cluster_id": "c1",
                        "family_label": "Indirect Injection",
                        "technique_family": "indirect_injection",
                        "scenario": "refund_tool",
                        "count": 1,
                        "example_match_ids": ["m01"],
                        "root_cause_summary": "Poisoned customer email.",
                    }
                ],
                recommended_defense="spotlighting+guard+output_filter",
                config_patch_yaml="defense: spotlighting+guard+output_filter\n",
                rationale="Stops email override.",
            )
        )
        await store.save_retrial_comparison(
            RetrialComparison(
                retrial_run_id="retrial-0002",
                baseline_run_id=run_started.run_id,
                matched_seeds=[101, 102],
                baseline_asr=0.5,
                retrial_asr=0.0,
                asr_delta=-0.5,
                baseline_utility=0.95,
                retrial_utility=0.95,
                per_scenario={"refund_tool": {"baseline_asr": 0.5, "retrial_asr": 0.0}},
            )
        )

    app = create_app(db_path=db_path, static_dir=tmp_path / "no_static")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get(f"/api/runs/{run_started.run_id}/bundle")
        assert res.status_code == 200
        payload = res.json()
        assert payload["summary"]["run_id"] == run_started.run_id
        assert payload["calibration"]["agreement_count"] == 5
        assert payload["advice"]["recommended_defense"] == "spotlighting+guard+output_filter"
        assert payload["retrial"]["per_scenario_diff"]["refund_tool"]["baseline_asr"] == 0.5

    html_doc = write_report(fmt="html", db_path=db_path, run_id=run_started.run_id)
    assert run_started.run_id in html_doc
    sarif_doc = json.loads(write_report(fmt="sarif", db_path=db_path, run_id=run_started.run_id))
    assert sarif_doc["version"] == "2.1.0"
    assert sarif_doc["runs"][0]["results"]
