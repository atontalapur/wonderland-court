"""Alice as a black-box agent: a Python callable you bring.

Court can't see inside an agent, so only input, output and guard defenses apply to it. An
agent never gets Court's system prompt either, which is where every scenario plants its
canary. Hooks let the agent take part anyway. Each one is passed only if the agent's function
has a parameter with that name, or takes `**kwargs`:

- `canary`: the match's `WC-` secret, read out of the scenario's system prompt. Plant it in the
  agent's own context so a leak can be caught exactly. `None` when the scenario has none.
- `document`: this turn's attachments, such as a Drink Me email, rendered the same way a model
  target sees them. `None` when there are none.
- `history`: the turns before this message, as `{"role": ..., "content": ...}` dicts, for agents
  that don't keep their own memory across a multi-turn attack.

A plain `respond(message: str) -> str` works too. An agent can return a `str`, a `TargetReply`,
or a dict with `content` and optional `tool_calls`. Tool calls use the shapes model targets
accept (`{"name", "arguments"}` or `{"function": {...}}`), and arguments for tools in the
scenario are coerced to their schema types, so the Queen still catches a `$400` refund.
"""

import asyncio
import importlib
import inspect
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import reduce
from time import perf_counter
from typing import Any

from wonderland_court.contracts import (
    TargetKind,
    TargetReply,
    TargetRequest,
    ToolCall,
    ToolSpec,
)
from wonderland_court.llm import tool_arguments

from .scenarios import CANARY_HEX_CHARS, CANARY_PREFIX
from .targets import calls_in, render_documents

HOOKS = ("canary", "document", "history")
_CANARY = re.compile(re.escape(CANARY_PREFIX) + f"[0-9a-f]{{{CANARY_HEX_CHARS}}}")


def find_canary(system_prompt: str) -> str | None:
    """The scenario's canary, as planted in its system prompt."""
    match = _CANARY.search(system_prompt)
    return match.group() if match else None


@dataclass(frozen=True)
class AgentTurn:
    """What an agent gets for one turn: the latest user message and the hooks."""

    message: str
    canary: str | None
    document: str | None
    history: list[dict[str, str]]

    @classmethod
    def from_request(cls, request: TargetRequest) -> "AgentTurn":
        messages = request.messages
        latest = next(
            (i for i in range(len(messages) - 1, -1, -1) if messages[i].role == "user"), None
        )
        earlier = messages if latest is None else messages[:latest]
        return cls(
            message="" if latest is None else messages[latest].content,
            canary=find_canary(request.system_prompt),
            document=render_documents(request.documents) or None,
            history=[{"role": m.role, "content": m.content} for m in earlier],
        )

    def hooks(self, accepted: frozenset[str]) -> dict[str, Any]:
        return {name: getattr(self, name) for name in HOOKS if name in accepted}


def agent_reply(value: Any, tools: Sequence[ToolSpec], source: str) -> TargetReply:
    """An agent's return value as a `TargetReply`, or a `TypeError` naming the agent."""
    if isinstance(value, TargetReply):
        return value
    if isinstance(value, str):
        return TargetReply(content=value)
    if isinstance(value, dict) and isinstance(value.get("content", ""), str):
        return TargetReply(
            content=value.get("content", ""),
            tool_calls=agent_tool_calls(value.get("tool_calls", []), tools),
        )
    raise TypeError(
        f"{source} returned {type(value).__name__} {value!r:.80}. Return a str, a TargetReply, "
        'or a dict like {"content": "...", "tool_calls": [...]}.'
    )


def agent_tool_calls(raw: Any, tools: Sequence[ToolSpec]) -> list[ToolCall]:
    """Structured tool calls from an agent. Calls to tools Court doesn't know are kept as-is."""
    schemas = {tool.name: tool.parameters for tool in tools}
    calls: list[ToolCall] = []
    for name, arguments in calls_in(raw):
        if name in schemas:
            arguments = tool_arguments(json.dumps(arguments), schemas[name])
        calls.append(ToolCall(id=f"call-{len(calls) + 1}", name=name, arguments=arguments))
    return calls


def _accepted_hooks(fn: Callable[..., Any]) -> frozenset[str]:
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):  # some builtins have no signature
        return frozenset()
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
        return frozenset(HOOKS)
    named = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    return frozenset(p.name for p in params[1:] if p.name in HOOKS and p.kind in named)


def load_entrypoint(entrypoint: str) -> Callable[..., Any]:
    """Import `module.path:callable`. The working directory is importable, as with uvicorn."""
    module_name, colon, attribute = entrypoint.partition(":")
    if not (colon and module_name and attribute):
        raise ValueError(
            f"python:{entrypoint} should look like python:module.path:callable, "
            "such as python:my_pkg.agent:respond."
        )
    cwd = os.getcwd()
    if "" not in sys.path and cwd not in sys.path:
        sys.path.insert(0, cwd)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"python:{entrypoint}: can't import {module_name!r}: {exc}") from exc
    try:
        fn = reduce(getattr, attribute.split("."), module)
    except AttributeError as exc:
        raise ValueError(
            f"python:{entrypoint}: {module_name!r} has no attribute {attribute!r}"
        ) from exc
    if not callable(fn):
        raise ValueError(f"python:{entrypoint}: {attribute!r} isn't callable")
    return fn


class PythonAgentTarget:
    """A black-box agent as a Python function, such as `python:my_pkg.agent:respond`."""

    kind = TargetKind.AGENT

    def __init__(self, entrypoint: str) -> None:
        self.name = f"python:{entrypoint}"
        self._fn = load_entrypoint(entrypoint)
        self._hooks = _accepted_hooks(self._fn)
        self._is_async = inspect.iscoroutinefunction(self._fn)

    async def respond(self, request: TargetRequest) -> TargetReply:
        turn = AgentTurn.from_request(request)
        hooks = turn.hooks(self._hooks)
        start = perf_counter()
        if self._is_async:
            value = await self._fn(turn.message, **hooks)
        else:
            # A sync agent may block on its own model call, so keep it off the event loop.
            value = await asyncio.to_thread(self._fn, turn.message, **hooks)
            if inspect.isawaitable(value):
                value = await value
        latency_ms = round((perf_counter() - start) * 1000)
        reply = agent_reply(value, request.tools, self.name)
        if reply.latency_ms:
            return reply
        return reply.model_copy(update={"latency_ms": latency_ms})
