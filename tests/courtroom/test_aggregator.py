"""Tests for Courtroom bundle aggregator and Wilson score interval math."""

from pathlib import Path

from wonderland_court.contracts import ScenarioId, read_events
from wonderland_court.courtroom.aggregator import build_bundle_from_events, wilson_interval

ROOT = Path(__file__).resolve().parents[2]
FAKE_RUN = ROOT / "fixtures" / "fake_run.jsonl"


def test_wilson_interval_bounds() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)
    lo0, hi0 = wilson_interval(0, 10)
    assert lo0 == 0.0 and 0.2 < hi0 < 0.35
    lo1, hi1 = wilson_interval(10, 10)
    assert 0.65 < lo1 < 0.8 and hi1 == 1.0


def test_build_bundle_from_fake_run() -> None:
    events = list(read_events(FAKE_RUN))
    bundle = build_bundle_from_events(events, source="jsonl")
    assert bundle.summary.run_id == "fake-run-0001"
    assert bundle.summary.status == "completed"
    assert bundle.summary.matches == 8
    assert bundle.summary.leaks == 3
    assert len(bundle.matches) == 8
    assert len(bundle.standings) == 4
    assert bundle.standings[0].defense == "spotlighting+guard+output_filter"
    assert bundle.heatmap.defenses == [
        "plain",
        "sandwich",
        "spotlighting",
        "spotlighting+guard+output_filter",
    ]
    assert ScenarioId.REFUND_TOOL in bundle.heatmap.scenarios
    plain_indirect = [
        c
        for c in bundle.heatmap.cells
        if c.defense == "plain"
        and c.family == "indirect_injection"
        and c.scenario is ScenarioId.REFUND_TOOL
    ]
    assert len(plain_indirect) == 1
    assert plain_indirect[0].leaks == 1
    assert plain_indirect[0].asr == 1.0
