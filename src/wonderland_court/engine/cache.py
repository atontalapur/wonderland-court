"""The LLM response cache.

The shared LLM client looks a reply up here before it calls a model, so a rerun with the same
seed replays instantly. The client builds the keys and decides what is cacheable; this module
only stores replies, through the store's single writer.
"""

from typing import Protocol

from ..contracts import TargetReply
from .store import CourtStore


class ResponseCache(Protocol):
    async def get(self, key: str) -> TargetReply | None: ...

    async def put(self, key: str, reply: TargetReply) -> None: ...


class SQLiteResponseCache:
    """A `ResponseCache` backed by the `llm_cache` table."""

    def __init__(self, store: CourtStore) -> None:
        self._store = store

    async def get(self, key: str) -> TargetReply | None:
        return await self._store.cache_get(key)

    async def put(self, key: str, reply: TargetReply) -> None:
        await self._store.cache_put(key, reply)
