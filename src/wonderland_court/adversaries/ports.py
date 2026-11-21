"""What the Adversaries track needs from outside it.

`ChatClient` and `EmbeddingClient` match the signatures issue #4 specifies for
`wonderland_court.llm.RateLimitedLLMClient`. They are Protocols, so the Engine
client fits without importing anything from here, and tests can pass fakes.

`Fuzzer` and `Poisoner` are the Mad Hatter and Drink Me seams the Cheshire Cat
calls. The Cat depends on these, not on the concrete classes.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from wonderland_court.contracts.models import (
    Document,
    Message,
    ScenarioId,
    TargetReply,
    ToolSpec,
    Turn,
)

Mutator = Callable[[str, random.Random], str]
"""A pure text transform. Same text and same seed give the same output."""


class ChatClient(Protocol):
    """Chat completion. Never sends `tool_choice` (Ollama `/v1` rejects it)."""

    async def chat(
        self,
        model_spec: str,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        tools: list[ToolSpec] | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> TargetReply: ...


class EmbeddingClient(Protocol):
    async def embed(
        self, texts: list[str], *, model: str = "nomic-embed-text"
    ) -> list[list[float]]: ...


class ModelClient(ChatClient, EmbeddingClient, Protocol):
    """Both halves of `wonderland_court.llm.LLMClient`, which the Engine registry passes in."""


class ModelConfig(Protocol):
    """The `court.yaml` fields the Adversaries factories read: a subset of `CourtConfig`."""

    @property
    def seed(self) -> int: ...
    @property
    def attacker_model(self) -> str: ...
    @property
    def judge_model(self) -> str: ...
    @property
    def embed_model(self) -> str: ...


class Fuzzer(Protocol):
    """The Mad Hatter. Returns the mutator ids applied and the mutated payload."""

    def mutate(
        self,
        payload: str,
        *,
        seed: int,
        mutators: list[str] | None = None,
        chain_len: int = 1,
    ) -> tuple[list[str], str]: ...


@runtime_checkable
class Evolver(Protocol):
    """A fuzzer that can also breed a payload from a match's near-miss turns."""

    def evolve_from_history(
        self, history: list[Turn], *, seed: int, mutators: list[str] | None = None
    ) -> tuple[list[str], str] | None: ...


class Poisoner(Protocol):
    """Drink Me. Hides an instruction inside a document Alice is asked to read."""

    def generate(
        self,
        scenario: ScenarioId,
        hidden_instruction: str,
        *,
        seed: int,
        kind: str | None = None,
    ) -> Document: ...
