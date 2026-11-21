"""JSONL Replay Mode store and paced SSE event streamer."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from wonderland_court.contracts import Event, read_events

from .aggregator import build_bundle_from_events
from .models import (
    CalibrationSummary,
    RemediationAdviceView,
    RetrialComparisonView,
    RunBundle,
)
from .sse import format_sse_event


def _load_sidecar_meta(replay_path: Path) -> dict[str, Any]:
    candidates = [
        Path(f"{replay_path}.meta.json"),
        replay_path.with_suffix(".meta.json"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
    return {}


class ReplayStore:
    """In-memory replay dataset loaded from a recorded `.jsonl` event log."""

    def __init__(self, replay_path: Path) -> None:
        self.replay_path = replay_path
        self.events: list[Event] = sorted(read_events(replay_path), key=lambda ev: ev.seq)
        meta = _load_sidecar_meta(replay_path)
        calibration = (
            CalibrationSummary.model_validate(meta["calibration"])
            if meta.get("calibration") is not None
            else None
        )
        advice = (
            RemediationAdviceView.model_validate(meta["advice"])
            if meta.get("advice") is not None
            else None
        )
        retrial = (
            RetrialComparisonView.model_validate(meta["retrial"])
            if meta.get("retrial") is not None
            else None
        )
        self.bundle: RunBundle = build_bundle_from_events(
            self.events,
            source="jsonl",
            calibration=calibration,
            advice=advice,
            retrial=retrial,
        )

    @property
    def run_id(self) -> str:
        return self.bundle.summary.run_id

    def get_events_after(self, after_seq: int = -1, limit: int = 500) -> list[Event]:
        """Return recorded events with `seq > after_seq`, up to `limit`."""
        if limit <= 0:
            return []
        return [ev for ev in self.events if ev.seq > after_seq][:limit]

    async def stream_events(
        self,
        *,
        speed: float = 4.0,
        from_seq: int = -1,
        max_delay: float = 1.2,
    ) -> AsyncIterator[str]:
        """Yield recorded events as SSE frames paced by their recorded timestamps."""
        filtered = [ev for ev in self.events if ev.seq > from_seq]
        if not filtered:
            return

        effective_speed = max(speed, 0.1)
        upper = max(0.0, max_delay)
        lower = min(0.04, upper)

        yield format_sse_event(filtered[0])
        for prev, curr in zip(filtered, filtered[1:], strict=False):
            raw_delta = max(0.0, (curr.ts - prev.ts).total_seconds())
            delay = min(upper, max(lower, raw_delta / effective_speed))
            if delay > 0.0:
                await asyncio.sleep(delay)
            yield format_sse_event(curr)
