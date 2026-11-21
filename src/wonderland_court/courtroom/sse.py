"""Server-Sent Events (SSE) formatting and live SQLite WAL tailing."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from wonderland_court.contracts import Event, dump_event

from .db_reader import CourtReadDB

SSE_HEARTBEAT = ": ping\n\n"


def format_sse_event(event: Event) -> str:
    """Format a single contract Event into an SSE frame."""
    return f"id: {event.seq}\nevent: {event.type}\ndata: {dump_event(event)}\n\n"


def resolve_after_seq(after_seq: int = -1, last_event_id: str | None = None) -> int:
    """Resolve effective `after_seq` cursor, honoring `Last-Event-ID` on reconnect."""
    if last_event_id is None:
        return after_seq
    try:
        parsed = int(last_event_id.strip())
    except ValueError:
        return after_seq
    return max(after_seq, parsed)


async def stream_live_events(
    reader: CourtReadDB,
    run_id: str,
    after_seq: int = -1,
    poll_interval: float = 0.15,
    heartbeat_interval: float = 15.0,
) -> AsyncIterator[str]:
    """Poll `reader` for new events on `run_id` and yield formatted SSE frames."""
    cursor = after_seq
    last_emit = time.monotonic()

    while True:
        events = await reader.get_events_after(run_id, after_seq=cursor, limit=500)
        if events:
            for event in events:
                cursor = event.seq
                yield format_sse_event(event)
            last_emit = time.monotonic()
            if len(events) == 500:
                await asyncio.sleep(0)
                continue
        elif time.monotonic() - last_emit >= heartbeat_interval:
            yield SSE_HEARTBEAT
            last_emit = time.monotonic()

        await asyncio.sleep(poll_interval)


async def stream_latest_live_events(
    reader: CourtReadDB,
    after_seq: int = -1,
    poll_interval: float = 0.15,
    heartbeat_interval: float = 15.0,
) -> AsyncIterator[str]:
    """Wait for a run to exist if needed, then tail the latest run's live event stream."""
    last_emit = time.monotonic()
    run_id: str | None = None

    while run_id is None:
        run_id = await reader.get_latest_run_id()
        if run_id is not None:
            break
        if time.monotonic() - last_emit >= heartbeat_interval:
            yield SSE_HEARTBEAT
            last_emit = time.monotonic()
        await asyncio.sleep(poll_interval)

    async for frame in stream_live_events(
        reader,
        run_id,
        after_seq=after_seq,
        poll_interval=poll_interval,
        heartbeat_interval=heartbeat_interval,
    ):
        yield frame
