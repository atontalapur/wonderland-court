"""Static site bundle exporter for GitHub Pages and offline Courtroom replay."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from wonderland_court.contracts import dump_event, read_events

from .models import RunBundle
from .reports import list_db_run_ids, load_report_bundle


def _validate_safe_run_id(run_id: str) -> str:
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise ValueError(f"Unsafe run_id for static export filename: {run_id!r}")
    return run_id


def _jsonl_run_ids(jsonl_path: Path) -> list[str]:
    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL input file not found: {jsonl_path}")
    seen: list[str] = []
    for ev in read_events(jsonl_path):
        if ev.run_id not in seen:
            seen.append(ev.run_id)
    return seen


def export_static_bundle(
    *,
    db_path: Path | None = None,
    jsonl_paths: Sequence[Path] = (),
    out_dir: Path,
) -> Path:
    """Export all runs from SQLite and/or JSONL inputs into a static Courtroom data bundle.

    Writes:
    - `<out_dir>/data/manifest.json`
    - `<out_dir>/data/runs/<run_id>.json`
    - `<out_dir>/data/runs/<run_id>.events.jsonl`
    """
    if db_path is None and not jsonl_paths:
        raise ValueError("Either db_path or at least one jsonl_path must be provided")

    bundles_by_id: dict[str, RunBundle] = {}

    if db_path is not None:
        for rid in list_db_run_ids(db_path):
            bundle = load_report_bundle(db_path=db_path, run_id=rid)
            bundles_by_id[bundle.summary.run_id] = bundle

    for jsonl_path in jsonl_paths:
        for rid in _jsonl_run_ids(jsonl_path):
            bundle = load_report_bundle(input_path=jsonl_path, run_id=rid)
            bundles_by_id[bundle.summary.run_id] = bundle

    if not bundles_by_id:
        raise ValueError("No runs found to export")

    data_dir = out_dir / "data"
    runs_dir = data_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    bundles = list(bundles_by_id.values())
    for bundle in bundles:
        rid = _validate_safe_run_id(bundle.summary.run_id)
        (runs_dir / f"{rid}.json").write_text(
            bundle.model_dump_json(indent=2),
            encoding="utf-8",
        )
        events_text = "\n".join(dump_event(ev) for ev in bundle.events)
        if events_text:
            events_text += "\n"
        (runs_dir / f"{rid}.events.jsonl").write_text(events_text, encoding="utf-8")

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "runs": [bundle.summary.model_dump(mode="json") for bundle in bundles],
    }
    (data_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return data_dir
