"""Per-IP sliding-window API rate limiter and concurrent SSE stream guard."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable


class IPRateLimiter:
    """Sliding 60-second per-IP request limiter and concurrent SSE connection tracker.

    All state updates execute synchronously without `await` points, making every check,
    acquire, and release atomic within a single asyncio event loop.
    """

    def __init__(
        self,
        max_requests_per_min: int = 120,
        max_sse_per_ip: int = 3,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests_per_min = max_requests_per_min
        self.max_sse_per_ip = max_sse_per_ip
        self._clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._sse_counts: dict[str, int] = defaultdict(int)

    def check_request(self, client_ip: str) -> tuple[bool, int]:
        """Record a request if under the 60s limit; return `(allowed, retry_after_seconds)`."""
        if self.max_requests_per_min <= 0:
            return (False, 60)

        now = self._clock()
        cutoff = now - 60.0
        dq = self._requests[client_ip]
        while dq and dq[0] <= cutoff:
            dq.popleft()

        if len(dq) >= self.max_requests_per_min:
            oldest = dq[0]
            retry_after = max(1, math.ceil(60.0 - (now - oldest)))
            return (False, retry_after)

        dq.append(now)
        return (True, 0)

    def acquire_sse(self, client_ip: str) -> bool:
        """Reserve an SSE stream slot for `client_ip`, returning False if at capacity."""
        if self.max_sse_per_ip <= 0:
            return False
        current = self._sse_counts.get(client_ip, 0)
        if current >= self.max_sse_per_ip:
            return False
        self._sse_counts[client_ip] = current + 1
        return True

    def release_sse(self, client_ip: str) -> None:
        """Release one active SSE stream slot for `client_ip`."""
        current = self._sse_counts.get(client_ip, 0)
        if current <= 1:
            self._sse_counts.pop(client_ip, None)
        else:
            self._sse_counts[client_ip] = current - 1

    def active_sse_count(self, client_ip: str) -> int:
        """Return the number of active SSE streams currently held by `client_ip`."""
        return self._sse_counts.get(client_ip, 0)
