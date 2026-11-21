"""FastAPI server, REST API, SSE live/replay streaming, and SPA static serving."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .db_reader import CourtReadDB
from .models import (
    CalibrationSummary,
    HeatmapData,
    RemediationAdviceView,
    RetrialComparisonView,
    RunBundle,
)
from .rate_limit import IPRateLimiter
from .replay import ReplayStore
from .sse import resolve_after_seq, stream_latest_live_events, stream_live_events

DEFAULT_DB_PATH = Path(".wonderland/court.db")
DEFAULT_STATIC_DIR = Path(__file__).resolve().parent / "static"

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _client_ip_from_scope(scope: Scope) -> str:
    client = scope.get("client")
    if isinstance(client, tuple | list) and len(client) >= 1 and isinstance(client[0], str):
        return client[0]
    return "unknown"


def _client_ip_from_request(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class _APIRateLimitMiddleware:
    """Pure ASGI middleware enforcing per-IP 60s `/api/*` rate limits without SSE buffering."""

    def __init__(self, app: ASGIApp, limiter: IPRateLimiter) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if path == "/api" or path.startswith("/api/"):
            client_ip = _client_ip_from_scope(scope)
            allowed, retry_after = self.limiter.check_request(client_ip)
            if not allowed:
                body = json.dumps({"detail": "Rate limit exceeded. Too many requests."}).encode(
                    "utf-8"
                )
                headers: list[tuple[bytes, bytes]] = [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"retry-after", str(retry_after).encode("ascii")),
                ]
                await send({"type": "http.response.start", "status": 429, "headers": headers})
                await send({"type": "http.response.body", "body": body, "more_body": False})
                return

        await self.app(scope, receive, send)


def _guarded_sse_response(
    client_ip: str,
    limiter: IPRateLimiter,
    stream: AsyncIterator[str],
) -> StreamingResponse:
    if not limiter.acquire_sse(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many concurrent SSE streams for this IP.",
            headers={"Retry-After": "5"},
        )

    async def _iterate() -> AsyncIterator[str]:
        try:
            async for frame in stream:
                yield frame
        finally:
            limiter.release_sse(client_ip)

    try:
        return StreamingResponse(
            _iterate(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )
    except Exception:
        limiter.release_sse(client_ip)
        raise


def create_app(
    *,
    db_path: Path | None = None,
    replay_path: Path | None = None,
    speed: float = 4.0,
    max_requests_per_min: int = 120,
    max_sse_per_ip: int = 3,
    static_dir: Path | None = None,
) -> FastAPI:
    """Create and configure the Courtroom FastAPI application."""
    app = FastAPI(title="Wonderland Court — Courtroom", version="0.1.0")
    limiter = IPRateLimiter(
        max_requests_per_min=max_requests_per_min,
        max_sse_per_ip=max_sse_per_ip,
    )
    reader = CourtReadDB(db_path if db_path is not None else DEFAULT_DB_PATH)
    replay_store = ReplayStore(replay_path) if replay_path is not None else None
    resolved_static_dir = static_dir if static_dir is not None else DEFAULT_STATIC_DIR

    app.state.limiter = limiter
    app.state.reader = reader
    app.state.replay_store = replay_store
    app.state.replay_speed = speed
    app.state.static_dir = resolved_static_dir

    app.add_middleware(_APIRateLimitMiddleware, limiter=limiter)

    api = APIRouter(prefix="/api")

    async def _resolve_run_id(run_id: str) -> str:
        if replay_store is not None:
            if run_id in (replay_store.run_id, "latest"):
                return replay_store.run_id
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
        if run_id == "latest":
            latest = await reader.get_latest_run_id()
            if latest is None:
                raise HTTPException(status_code=404, detail="No runs available.")
            return latest
        return run_id

    async def _load_bundle(run_id: str) -> RunBundle:
        resolved = await _resolve_run_id(run_id)
        if replay_store is not None:
            return replay_store.bundle
        bundle = await reader.get_run_bundle(resolved)
        if bundle is None:
            raise HTTPException(status_code=404, detail=f"Run '{resolved}' not found.")
        return bundle

    @api.get("/health")
    async def health() -> dict[str, Any]:
        db_ready = await reader.is_ready()
        return {
            "status": "ok",
            "mode": "replay" if replay_store is not None else "live",
            "db_ready": db_ready,
            "replay_speed": speed,
        }

    @api.get("/runs")
    async def list_runs() -> dict[str, list[dict[str, Any]]]:
        if replay_store is not None:
            return {"runs": [replay_store.bundle.summary.model_dump(mode="json")]}
        runs = await reader.list_runs()
        return {"runs": [r.model_dump(mode="json") for r in runs]}

    @api.get("/runs/{run_id}/bundle")
    async def get_run_bundle(run_id: str) -> dict[str, Any]:
        bundle = await _load_bundle(run_id)
        return bundle.model_dump(mode="json")

    @api.get("/runs/{run_id}/events")
    async def get_run_events(
        run_id: str,
        after_seq: int = -1,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, list[dict[str, Any]]]:
        resolved = await _resolve_run_id(run_id)
        if replay_store is not None:
            events = replay_store.get_events_after(after_seq=after_seq, limit=limit)
        else:
            events = await reader.get_events_after(resolved, after_seq=after_seq, limit=limit)
        return {"events": [ev.model_dump(mode="json") for ev in events]}

    @api.get("/runs/{run_id}/standings")
    async def get_run_standings(run_id: str) -> dict[str, Any]:
        bundle = await _load_bundle(run_id)
        return {
            "run_id": bundle.summary.run_id,
            "standings": [s.model_dump(mode="json") for s in bundle.standings],
        }

    @api.get("/runs/{run_id}/heatmap")
    async def get_run_heatmap(run_id: str) -> dict[str, Any]:
        bundle = await _load_bundle(run_id)
        heatmap: HeatmapData = bundle.heatmap
        return heatmap.model_dump(mode="json")

    @api.get("/runs/{run_id}/calibration")
    async def get_run_calibration(run_id: str) -> dict[str, Any] | None:
        resolved = await _resolve_run_id(run_id)
        cal: CalibrationSummary | None
        if replay_store is not None:
            cal = replay_store.bundle.calibration
        else:
            cal = await reader.get_calibration(resolved)
        return cal.model_dump(mode="json") if cal is not None else None

    @api.get("/runs/{run_id}/advice")
    async def get_run_advice(run_id: str) -> dict[str, Any] | None:
        resolved = await _resolve_run_id(run_id)
        adv: RemediationAdviceView | None
        if replay_store is not None:
            adv = replay_store.bundle.advice
        else:
            adv = await reader.get_advice(resolved)
        return adv.model_dump(mode="json") if adv is not None else None

    @api.get("/runs/{run_id}/retrial-diff")
    async def get_run_retrial_diff(run_id: str) -> dict[str, Any] | None:
        resolved = await _resolve_run_id(run_id)
        diff: RetrialComparisonView | None
        if replay_store is not None:
            diff = replay_store.bundle.retrial
        else:
            diff = await reader.get_retrial_diff(resolved)
        return diff.model_dump(mode="json") if diff is not None else None

    @api.get("/runs/{run_id}/stream")
    async def stream_run(
        run_id: str,
        request: Request,
        after_seq: int = -1,
        stream_speed: float | None = Query(default=None, alias="speed", gt=0.0),
        max_delay: float = Query(default=1.2, ge=0.0, le=10.0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        effective_after = resolve_after_seq(after_seq=after_seq, last_event_id=last_event_id)
        client_ip = _client_ip_from_request(request)

        if replay_store is not None:
            if run_id not in (replay_store.run_id, "latest"):
                raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
            effective_speed = stream_speed if stream_speed is not None else speed
            stream = replay_store.stream_events(
                speed=effective_speed,
                from_seq=effective_after,
                max_delay=max_delay,
            )
        else:
            resolved = await _resolve_run_id(run_id)
            stream = stream_live_events(reader, resolved, after_seq=effective_after)

        return _guarded_sse_response(client_ip, limiter, stream)

    @api.get("/stream/latest")
    async def stream_latest(
        request: Request,
        after_seq: int = -1,
        stream_speed: float | None = Query(default=None, alias="speed", gt=0.0),
        max_delay: float = Query(default=1.2, ge=0.0, le=10.0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        effective_after = resolve_after_seq(after_seq=after_seq, last_event_id=last_event_id)
        client_ip = _client_ip_from_request(request)

        if replay_store is not None:
            effective_speed = stream_speed if stream_speed is not None else speed
            stream = replay_store.stream_events(
                speed=effective_speed,
                from_seq=effective_after,
                max_delay=max_delay,
            )
        else:
            stream = stream_latest_live_events(reader, after_seq=effective_after)

        return _guarded_sse_response(client_ip, limiter, stream)

    @api.get("/replay/stream")
    async def stream_replay(
        request: Request,
        stream_speed: float | None = Query(default=None, alias="speed", gt=0.0),
        from_seq: int = -1,
        max_delay: float = Query(default=1.2, ge=0.0, le=10.0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        if replay_store is None:
            raise HTTPException(status_code=404, detail="Replay mode is not enabled.")
        effective_after = resolve_after_seq(after_seq=from_seq, last_event_id=last_event_id)
        effective_speed = stream_speed if stream_speed is not None else speed
        client_ip = _client_ip_from_request(request)
        stream = replay_store.stream_events(
            speed=effective_speed,
            from_seq=effective_after,
            max_delay=max_delay,
        )
        return _guarded_sse_response(client_ip, limiter, stream)

    app.include_router(api)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> Response:
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        index_file = resolved_static_dir / "index.html"
        if not index_file.is_file():
            return HTMLResponse(
                content=(
                    "<!doctype html><html><head><title>Wonderland Court</title></head>"
                    "<body><h1>Wonderland Court — Courtroom API</h1>"
                    "<p>Frontend static bundle is not built yet. "
                    "Check <a href='/api/health'>/api/health</a>.</p></body></html>"
                ),
                status_code=200,
            )

        if full_path:
            static_root = resolved_static_dir.resolve()
            candidate = (static_root / full_path).resolve()
            if candidate.is_relative_to(static_root) and candidate.is_file():
                return FileResponse(candidate)

        return FileResponse(index_file)

    return app


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    replay: Path | None = None,
    speed: float = 4.0,
    db_path: Path | None = None,
) -> None:
    """Start the Courtroom FastAPI server with uvicorn."""
    app = create_app(db_path=db_path, replay_path=replay, speed=speed)
    uvicorn.run(app, host=host, port=port)
