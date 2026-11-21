"""Tests for static site bundle exporter (GitHub Pages / 4x client replay)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from wonderland_court.contracts import dump_event, parse_event, read_events
from wonderland_court.courtroom.models import RunBundle, RunSummary
from wonderland_court.courtroom.static_site import export_static_bundle

ROOT = Path(__file__).resolve().parents[2]
FAKE_RUN = ROOT / "fixtures" / "fake_run.jsonl"


def test_export_static_bundle_from_jsonl(tmp_path: Path) -> None:
    out_dir = tmp_path / "web" / "public"
    data_dir = export_static_bundle(jsonl_paths=[FAKE_RUN], out_dir=out_dir)

    assert data_dir == out_dir / "data"
    manifest_path = out_dir / "data" / "manifest.json"
    bundle_path = out_dir / "data" / "runs" / "fake-run-0001.json"
    events_path = out_dir / "data" / "runs" / "fake-run-0001.events.jsonl"

    assert manifest_path.exists()
    assert bundle_path.exists()
    assert events_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "generated_at" in manifest
    assert len(manifest["runs"]) == 1
    summary = RunSummary.model_validate(manifest["runs"][0])
    assert summary.run_id == "fake-run-0001"
    assert summary.matches == 8
    assert summary.leaks == 3

    bundle = RunBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
    assert bundle.summary.run_id == "fake-run-0001"
    assert len(bundle.matches) == 8

    replay_lines = [
        line for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(replay_lines) == 79
    parsed_events = [parse_event(line) for line in replay_lines]
    assert parsed_events[0].type == "run_started"
    assert parsed_events[-1].type == "run_ended"


def test_export_static_bundle_from_sqlite_and_jsonl(tmp_path: Path) -> None:
    events = list(read_events(FAKE_RUN))
    db_path = tmp_path / "court.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, started_at TEXT)")
    conn.execute("CREATE TABLE events (seq INTEGER, run_id TEXT, payload TEXT)")

    for idx, rid in enumerate(["sqlite-run-1", "sqlite-run-2"]):
        conn.execute(
            "INSERT INTO runs (run_id, started_at) VALUES (?, ?)",
            (rid, f"2026-11-21T1{idx}:00:00Z"),
        )
        for ev in events:
            rewritten = parse_event(json.dumps({**json.loads(dump_event(ev)), "run_id": rid}))
            conn.execute(
                "INSERT INTO events (seq, run_id, payload) VALUES (?, ?, ?)",
                (rewritten.seq, rid, dump_event(rewritten)),
            )

    conn.commit()
    conn.close()

    out_dir = tmp_path / "site"
    export_static_bundle(db_path=db_path, jsonl_paths=[FAKE_RUN], out_dir=out_dir)

    manifest = json.loads((out_dir / "data" / "manifest.json").read_text(encoding="utf-8"))
    run_ids = [r["run_id"] for r in manifest["runs"]]
    assert run_ids == ["sqlite-run-1", "sqlite-run-2", "fake-run-0001"]

    for rid in run_ids:
        assert (out_dir / "data" / "runs" / f"{rid}.json").exists()
        assert (out_dir / "data" / "runs" / f"{rid}.events.jsonl").exists()


def test_export_static_bundle_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Either db_path or at least one jsonl_path"):
        export_static_bundle(out_dir=tmp_path)

    bad_jsonl = tmp_path / "bad.jsonl"
    ev = next(read_events(FAKE_RUN))
    bad_ev = parse_event(json.dumps({**json.loads(dump_event(ev)), "run_id": "../escape"}))
    bad_jsonl.write_text(dump_event(bad_ev) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsafe run_id"):
        export_static_bundle(jsonl_paths=[bad_jsonl], out_dir=tmp_path / "out")
