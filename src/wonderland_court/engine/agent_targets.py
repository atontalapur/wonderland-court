"""Alice as a black-box agent you bring: a Python callable or an HTTP endpoint.

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

An HTTP agent gets the same four values as placeholders in `request_template`: `{{message}}`,
`{{canary}}`, `{{document}}` and `{{history}}`. A string that is only a placeholder becomes
the raw value, so `"{{history}}"` sends a JSON list and a missing canary sends `null`. Inside
longer text a missing value renders as nothing. Templates are Jinja2, so filters like
`{{ history | tojson }}` work. The URL and headers can use `${ENV_VAR}`. Error messages name the
unexpanded URL and never include header values or response bodies, so secrets stay out of logs.

HTTP agents are rate limited like model calls, with lanes of their own so a slow agent can't
starve the attacker or the judge. Local endpoints get 2 requests at a time and no retries.
Remote endpoints get 4 at a time and 60 in any 60 seconds, and retry only 429, 503 and
connection failures, honoring `Retry-After`. Other errors aren't retried, because the agent
may already have acted: a retried refund is a second refund.
"""

import asyncio
import importlib
import inspect
import json
import os
import random
import re
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import reduce
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

import httpx
from jinja2 import StrictUndefined, TemplateSyntaxError, meta
from jinja2.sandbox import SandboxedEnvironment

from wonderland_court.config import HttpTargetConfig
from wonderland_court.contracts import (
    TargetKind,
    TargetReply,
    TargetRequest,
    ToolCall,
    ToolSpec,
)
from wonderland_court.llm import (
    LOCAL_HOSTS,
    REQUEST_TIMEOUT_S,
    Lane,
    Limits,
    SlidingWindow,
    tool_arguments,
)

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


# HTTP agents

PLACEHOLDERS = frozenset({"message", *HOOKS})
RETRY_STATUS = frozenset({429, 503})
DEFAULT_LIMITS = Limits()
_ENV_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_LONE_PLACEHOLDER = re.compile(r"\s*\{\{\s*(\w+)\s*\}\}\s*")
_JINJA = SandboxedEnvironment(
    undefined=StrictUndefined,
    autoescape=False,
    finalize=lambda value: "" if value is None else value,
)

Renderer = Callable[[dict[str, Any]], Any]


class AgentHTTPError(RuntimeError):
    """An HTTP agent failed. The message names the agent and never includes a secret."""


def expand_env(text: str, where: str) -> str:
    """Fill in `${ENV_VAR}` from the environment. An unset variable is named, never guessed."""

    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise ValueError(f"{where} uses ${{{name}}}, but {name} isn't set.")
        return os.environ[name]

    return _ENV_VAR.sub(value, text)


def compile_template(template: Any, source: str) -> Renderer:
    """Compile a JSON request template once. Unknown placeholders fail here, not mid-match."""
    if isinstance(template, dict):
        fields = {key: compile_template(value, source) for key, value in template.items()}
        return lambda values: {key: render(values) for key, render in fields.items()}
    if isinstance(template, list):
        items = [compile_template(item, source) for item in template]
        return lambda values: [render(values) for render in items]
    if not isinstance(template, str):
        return lambda values: template
    try:
        names = meta.find_undeclared_variables(_JINJA.parse(template))
    except TemplateSyntaxError as exc:
        raise ValueError(f"{source}: can't read request_template {template!r}: {exc}") from exc
    unknown = names - PLACEHOLDERS
    if unknown:
        raise ValueError(
            f"{source}: request_template uses {', '.join(sorted(unknown))}. "
            f"The placeholders are {', '.join(sorted(PLACEHOLDERS))}."
        )
    if lone := _LONE_PLACEHOLDER.fullmatch(template):
        name = lone.group(1)
        return lambda values: values[name]
    if not names:
        return lambda values: template
    compiled = _JINJA.from_string(template)
    return lambda values: compiled.render(values)


def dig(data: Any, path: str) -> Any:
    """The value at a dotted path such as `choices.0.message.content`, or a `KeyError`."""
    value = data
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise KeyError(path)
    return value


class AgentLanes:
    """Concurrency, pacing and backoff for HTTP agents, shared by every HTTP agent target."""

    def __init__(
        self,
        limits: Limits = DEFAULT_LIMITS,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        self.limits = limits
        self.sleep = sleep
        self.local = Lane(limits.local_concurrency)
        self.remote = Lane(
            limits.remote_concurrency, SlidingWindow(limits.remote_per_minute, sleep=sleep)
        )


_default_lanes: AgentLanes | None = None


def default_agent_lanes() -> AgentLanes:
    global _default_lanes
    if _default_lanes is None:
        _default_lanes = AgentLanes()
    return _default_lanes


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


class HttpAgentTarget:
    """A black-box agent behind an HTTP endpoint. Its name is the URL as configured."""

    kind = TargetKind.AGENT

    def __init__(self, config: HttpTargetConfig, lanes: AgentLanes | None = None) -> None:
        self.name = config.url
        self._url = expand_env(config.url, f"{config.url}: url")
        self._headers = {
            key: expand_env(value, f"{config.url}: header {key!r}")
            for key, value in config.headers.items()
        }
        self._body = compile_template(config.request_template, config.url)
        self._response_path = config.response_path
        self._tool_calls_path = config.tool_calls_path
        self._lanes = lanes or default_agent_lanes()
        self._local = urlparse(self._url).hostname in LOCAL_HOSTS

    async def respond(self, request: TargetRequest) -> TargetReply:
        turn = AgentTurn.from_request(request)
        body = self._body({"message": turn.message, **turn.hooks(PLACEHOLDERS)})
        start = perf_counter()
        response = await self._post(body)
        latency_ms = round((perf_counter() - start) * 1000)
        try:
            data = response.json()
        except ValueError:
            data = None
        if data is None:
            raise AgentHTTPError(
                f"{self.name} replied with HTTP {response.status_code}, but not with JSON."
            )
        try:
            content = dig(data, self._response_path)
        except KeyError:
            raise ValueError(
                f"{self.name}: the response has nothing at {self._response_path!r}. "
                "Set response_path to where the reply text is."
            ) from None
        tool_calls: Any = []
        if self._tool_calls_path:
            try:
                tool_calls = dig(data, self._tool_calls_path)
            except KeyError:
                tool_calls = []
        reply = agent_reply(
            {"content": content, "tool_calls": tool_calls}, request.tools, self.name
        )
        return reply.model_copy(update={"latency_ms": latency_ms})

    async def _post(self, body: Any) -> httpx.Response:
        lanes = self._lanes
        lane = lanes.local if self._local else lanes.remote
        attempt = 0
        while True:
            # Errors are raised outside the except blocks, so no httpx exception (which carries
            # the expanded URL) rides along as context.
            response: httpx.Response | None = None
            try:
                async with lane.slot(), httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
                    response = await client.post(self._url, json=body, headers=self._headers)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # The request never reached the agent, so it is safe to send again.
                failure, retryable = f"{self.name}: can't connect ({type(exc).__name__}).", True
            except httpx.TransportError as exc:
                # The agent may have read the request and acted on it, so don't send it again.
                failure, retryable = f"{self.name}: request failed ({type(exc).__name__}).", False
            if response is not None:
                if response.status_code < 400:
                    return response
                failure = f"{self.name} replied with HTTP {response.status_code}."
                retryable = response.status_code in RETRY_STATUS
            if self._local or not retryable or attempt >= lanes.limits.max_retries:
                raise AgentHTTPError(failure)
            delay = _retry_after(response) if response is not None else None
            if delay is None:
                ceiling = min(lanes.limits.backoff_cap_s, lanes.limits.backoff_base_s * 2**attempt)
                delay = random.uniform(0, ceiling)
            await lanes.sleep(delay)
            attempt += 1
