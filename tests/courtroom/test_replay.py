"""Tests for Courtroom JSONL Replay Mode and sidecar Wave 2 metadata."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from wonderland_court.contracts import Event, ScenarioId, parse_event
from wonderland_court.courtroom.models import (
    CalibrationSummary,
    FailureClusterView,
    RemediationAdviceView,
    RetrialComparisonView,
)
from wonderland_court.courtroom.replay import ReplayStore
from wonderland_court.courtroom.server import create_app

ROOT = Path(__file__).resolve().parents[2]
FAKE_RUN = ROOT / "fixtures" / "fake_run.jsonl"


def _parse_sse_frames(raw_text: str) -> list[tuple[str, str, Event]]:
    frames: list[tuple[str, str, Event]] = []
    for block in raw_text.strip().split("\n\n"):
        if not block.strip() or block.strip().startswith(":"):
            continue
        event_id = ""
        event_type = ""
        data_line = ""
        for line in block.splitlines():
            if line.startswith("id: "):
                event_id = line[4:]
            elif line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_line = line[6:]
        frames.append((event_id, event_type, parse_event(data_line)))
    return frames


def test_replay_store_loads_fake_run() -> None:
    store = ReplayStore(FAKE_RUN)
    assert store.run_id == "fake-run-0001"
    assert len(store.events) == 79
    assert store.bundle.summary.source == "jsonl"
    assert store.bundle.summary.matches == 8
    assert store.bundle.summary.leaks == 3
    assert store.bundle.calibration is None
    assert store.bundle.advice is None
    assert store.bundle.retrial is None


def test_replay_store_loads_sidecar_wave2_metadata(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "demo_run.jsonl"
    jsonl_path.write_text(FAKE_RUN.read_text(encoding="utf-8"), encoding="utf-8")

    cal = CalibrationSummary(
        run_id="fake-run-0001",
        total_exact_checked=8,
        llm_evaluated=5,
        agreement_count=5,
        agreement_rate=1.0,
        false_positives=0,
        false_negatives=0,
    )
    adv = RemediationAdviceView(
        run_id="fake-run-0001",
        target_kind="model",
        clusters=[
            FailureClusterView(
                cluster_id="c1",
                family_label="Indirect Document Injection",
                technique_family="indirect_injection",
                scenario=ScenarioId.REFUND_TOOL,
                count=1,
                example_match_ids=["m01"],
                root_cause_summary="Trusted HTML comments in email bodies.",
            )
        ],
        recommended_defense="spotlighting+guard+output_filter",
        config_patch_yaml="defense: spotlighting+guard+output_filter\n",
        rationale="Eliminated all leaks across tested scenarios.",
    )
    ret = RetrialComparisonView(
        baseline_run_id="fake-run-0001",
        retrial_run_id="retrial-0002",
        matched_seeds=[2751, 504],
        baseline_asr=0.375,
        retrial_asr=0.0,
        asr_delta=-0.375,
        baseline_utility=0.95,
        retrial_utility=0.94,
        per_scenario_diff={"refund_tool": {"baseline": 0.25, "retrial": 0.0}},
    )

    sidecar = tmp_path / "demo_run.jsonl.meta.json"
    sidecar.write_text(
        json.dumps(
            {
                "calibration": cal.model_dump(mode="json"),
                "advice": adv.model_dump(mode="json"),
                "retrial": ret.model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )

    store = ReplayStore(jsonl_path)
    assert store.bundle.calibration == cal
    assert store.bundle.advice == adv
    assert store.bundle.retrial == ret


@pytest.mark.asyncio
async def test_replay_store_stream_events_and_resume() -> None:
    store = ReplayStore(FAKE_RUN)
    frames = [frame async for frame in store.stream_events(speed=4.0, from_seq=-1, max_delay=0.0)]
    assert len(frames) == 79
    parsed = _parse_sse_frames("".join(frames))
    assert [ev.seq for _, _, ev in parsed] == list(range(79))

    resumed = [frame async for frame in store.stream_events(speed=4.0, from_seq=75, max_delay=0.0)]
    parsed_resumed = _parse_sse_frames("".join(resumed))
    assert [ev.seq for _, _, ev in parsed_resumed] == [76, 77, 78]


@pytest.mark.asyncio
async def test_replay_http_endpoints_and_sse_stream() -> None:
    app = create_app(replay_path=FAKE_RUN, speed=4.0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["mode"] == "replay"
        assert health.json()["replay_speed"] == 4.0

        runs = await client.get("/api/runs")
        assert runs.status_code == 200
        assert len(runs.json()["runs"]) == 1
        assert runs.json()["runs"][0]["run_id"] == "fake-run-0001"

        bundle = await client.get("/api/runs/fake-run-0001/bundle")
        assert bundle.status_code == 200
        assert len(bundle.json()["events"]) == 79

        replay_sse = await client.get("/api/replay/stream?speed=10.0&from_seq=-1&max_delay=0.0")
        assert replay_sse.status_code == 200
        assert replay_sse.headers["content-type"].startswith("text/event-stream")
        parsed = _parse_sse_frames(replay_sse.text)
        assert len(parsed) == 79
        assert [ev.seq for _, _, ev in parsed] == list(range(79))

        resumed_sse = await client.get(
            "/api/runs/fake-run-0001/stream?max_delay=0.0",
            headers={"Last-Event-ID": "76"},
        )
        assert resumed_sse.status_code == 200
        resumed_parsed = _parse_sse_frames(resumed_sse.text)
        assert [ev.seq for _, _, ev in resumed_parsed] == [77, 78]

        latest_sse = await client.get("/api/stream/latest?max_delay=0.0&after_seq=77")
        assert latest_sse.status_code == 200
        latest_parsed = _parse_sse_frames(latest_sse.text)
        assert [ev.seq for _, _, ev in latest_parsed] == [78]

        missing_run = await client.get("/api/runs/unknown-run/bundle")
        assert missing_run.status_code == 404
