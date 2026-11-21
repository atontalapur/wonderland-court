"""One rate-limited client for every model call: targets, the guard, the Cat, the Queen and the
Caterpillar all share it, so a laptop never runs more local calls at once than it can hold.

Limits, from the plan:
- Local endpoints (localhost or 127.0.0.1): 2 calls at a time. No retries, so a stopped Ollama
  fails fast instead of hanging.
- Remote endpoints: 4 calls at a time and 60 calls in any 60-second window, with jittered
  exponential backoff on 408, 409, 429, 5xx and connection errors.

Model specs:
- `ollama:<model>`, or a bare name like `qwen3.5:4b`. Anything without a known provider prefix
  is an Ollama model.
- `openai:<model>` and `anthropic:<model>`, with keys from OPENAI_API_KEY and ANTHROPIC_API_KEY.
- `openai-compat:<base_url>|<model>` for vLLM, LM Studio, OpenRouter, Groq and the like.

Ollama quirks, measured in the spike posted on #8:
- `tool_choice` is accepted but not enforced, so it is never sent. Nothing may depend on it.
- Thinking models such as qwen3.5 spend the whole token budget reasoning and return empty
  content, so Ollama calls send `reasoning_effort: "none"`. It is harmless on other models.
- llama3.1 sometimes sends numbers as strings (`"amount": "12"`), so tool arguments are coerced
  to the types the tool's JSON Schema declares.
"""

import asyncio
import hashlib
import json
import os
import random
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar, cast
from urllib.parse import urlparse

import anthropic
import httpx2
import openai
from anthropic.types import MessageParam
from openai.types.chat import ChatCompletionMessageParam

from wonderland_court.contracts import Message, TargetReply, ToolCall, ToolSpec

Provider = Literal["ollama", "openai", "anthropic", "openai-compat"]
PROVIDERS: frozenset[str] = frozenset({"ollama", "openai", "anthropic", "openai-compat"})
AGENT_PREFIXES: frozenset[str] = frozenset({"python", "http", "https"})
LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})
RETRY_STATUS: frozenset[int] = frozenset({408, 409, 429})
OLLAMA_EXTRA_BODY: dict[str, Any] = {"reasoning_effort": "none"}
ANTHROPIC_MAX_TOKENS = 1024
REQUEST_TIMEOUT_S = 180.0


def ollama_base_url() -> str:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    if "://" not in host:
        host = f"http://{host}"
    return f"{host.rstrip('/')}/v1"


# Model specs


@dataclass(frozen=True)
class ModelSpec:
    provider: Provider
    model: str
    base_url: str | None = None
    """None means the provider's default endpoint."""

    @property
    def canonical(self) -> str:
        if self.provider == "openai-compat":
            return f"openai-compat:{self.base_url}|{self.model}"
        return f"{self.provider}:{self.model}"

    @property
    def is_local(self) -> bool:
        return self.base_url is not None and urlparse(self.base_url).hostname in LOCAL_HOSTS


def parse_model_spec(spec: str) -> ModelSpec:
    prefix, sep, rest = spec.partition(":")
    if sep and prefix in AGENT_PREFIXES:
        raise ValueError(f"{spec!r} is an agent target, not a model the LLM client can call")
    if not sep or prefix not in PROVIDERS:
        return ModelSpec("ollama", spec, ollama_base_url())
    if not rest:
        raise ValueError(f"{spec!r} is missing a model name")
    if prefix == "ollama":
        return ModelSpec("ollama", rest, ollama_base_url())
    if prefix == "openai-compat":
        base_url, bar, model = rest.partition("|")
        if not bar or not base_url or not model:
            raise ValueError(f"{spec!r} should look like openai-compat:<base_url>|<model>")
        return ModelSpec("openai-compat", model, base_url)
    return ModelSpec(prefix, rest)  # type: ignore[arg-type]  # openai or anthropic


# Cache


class ResponseCache(Protocol):
    """Implemented by the store (#7). The client computes the key with `cache_key`."""

    async def get(self, key: str) -> TargetReply | None: ...

    async def put(self, key: str, reply: TargetReply) -> None: ...


def cache_key(
    model_spec: str,
    messages: list[Message],
    *,
    system_prompt: str | None,
    tools: list[ToolSpec] | None,
    json_schema: dict[str, Any] | None,
    temperature: float,
    seed: int | None,
) -> str:
    payload = {
        "v": 1,
        "model": parse_model_spec(model_spec).canonical,
        "system_prompt": system_prompt,
        "messages": [m.model_dump(mode="json") for m in messages],
        "tools": [t.model_dump(mode="json") for t in tools or []],
        "json_schema": json_schema,
        "temperature": temperature,
        "seed": seed,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


# Rate limiting


class SlidingWindow:
    """Allows at most `max_calls` starts in any `period`-second window."""

    def __init__(
        self,
        max_calls: int,
        period: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        self.max_calls = max_calls
        self.period = period
        self._clock = clock
        self._sleep = sleep
        self._starts: deque[float] = deque()
        self._lock: asyncio.Lock | None = None

    async def acquire(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            while True:
                now = self._clock()
                while self._starts and now - self._starts[0] >= self.period:
                    self._starts.popleft()
                if len(self._starts) < self.max_calls:
                    self._starts.append(now)
                    return
                await self._sleep(self.period - (now - self._starts[0]))


class Lane:
    """Concurrency (and, for remote calls, pacing) for one class of endpoint."""

    def __init__(self, concurrency: int, window: SlidingWindow | None = None) -> None:
        self.concurrency = concurrency
        self.window = window
        self.active = 0
        self.peak = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._semaphore: asyncio.Semaphore | None = None

    def _bind(self) -> asyncio.Semaphore:
        # asyncio primitives belong to one event loop. Rebuild them if a new loop shows up,
        # as happens when tests or separate `asyncio.run` calls share the default client.
        loop = asyncio.get_running_loop()
        if self._semaphore is None or loop is not self._loop:
            self._loop = loop
            self._semaphore = asyncio.Semaphore(self.concurrency)
            if self.window is not None:
                self.window._lock = None
        return self._semaphore

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._bind():
            if self.window is not None:
                await self.window.acquire()
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                yield
            finally:
                self.active -= 1


@dataclass(frozen=True)
class Limits:
    local_concurrency: int = 2
    remote_concurrency: int = 4
    remote_per_minute: int = 60
    max_retries: int = 4
    backoff_base_s: float = 0.5
    backoff_cap_s: float = 8.0


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, openai.APIConnectionError | anthropic.APIConnectionError):
        return True
    if isinstance(exc, openai.APIStatusError | anthropic.APIStatusError):
        return exc.status_code in RETRY_STATUS or exc.status_code >= 500
    return False


# Provider backends


class Backend(Protocol):
    async def chat(
        self,
        spec: ModelSpec,
        messages: list[Message],
        *,
        system_prompt: str | None,
        tools: list[ToolSpec] | None,
        json_schema: dict[str, Any] | None,
        temperature: float,
        seed: int | None,
    ) -> TargetReply: ...

    async def embed(self, spec: ModelSpec, texts: list[str]) -> list[list[float]]: ...


def _coerce(value: Any, schema_type: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip().lstrip("$").replace(",", "")
    try:
        if schema_type == "integer":
            number = float(text)
            return int(number) if number.is_integer() else number
        if schema_type == "number":
            return float(text)
    except ValueError:
        return value
    if schema_type == "boolean" and text.lower() in {"true", "false"}:
        return text.lower() == "true"
    return value


def tool_arguments(raw: str | None, parameters: dict[str, Any] | None) -> dict[str, Any]:
    """Parse a tool call's JSON arguments and coerce top-level values to the schema's types."""
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_unparsed": raw}
    if not isinstance(parsed, dict):
        return {"_unparsed": raw}
    properties = (parameters or {}).get("properties", {})
    return {
        name: _coerce(value, properties.get(name, {}).get("type")) for name, value in parsed.items()
    }


class OpenAIBackend:
    """Ollama, OpenAI and every OpenAI-compatible server."""

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        extra_body: dict[str, Any] | None = None,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        # Retries are ours, so the SDK's own are off.
        self._client = openai.AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,
            timeout=REQUEST_TIMEOUT_S,
            http_client=http_client,
        )
        self._extra_body = extra_body

    async def chat(
        self,
        spec: ModelSpec,
        messages: list[Message],
        *,
        system_prompt: str | None,
        tools: list[ToolSpec] | None,
        json_schema: dict[str, Any] | None,
        temperature: float,
        seed: int | None,
    ) -> TargetReply:
        wire: list[dict[str, Any]] = []
        if system_prompt is not None:
            wire.append({"role": "system", "content": system_prompt})
        for message in messages:
            item: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.tool_call_id is not None:
                item["tool_call_id"] = message.tool_call_id
            wire.append(item)
        kwargs: dict[str, Any] = {"temperature": temperature}
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        if seed is not None:
            kwargs["seed"] = seed
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters or {"type": "object", "properties": {}},
                    },
                }
                for tool in tools
            ]
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema},
            }
        started = time.perf_counter()
        response = await self._client.chat.completions.create(
            model=spec.model, messages=cast(list[ChatCompletionMessageParam], wire), **kwargs
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
        message_out = response.choices[0].message
        schemas = {tool.name: tool.parameters for tool in tools or []}
        calls = [
            ToolCall(
                id=call.id or f"call-{index}",
                name=call.function.name,
                arguments=tool_arguments(call.function.arguments, schemas.get(call.function.name)),
            )
            for index, call in enumerate(message_out.tool_calls or [])
            if call.type == "function"
        ]
        return TargetReply(
            content=message_out.content or "", tool_calls=calls, latency_ms=latency_ms
        )

    async def embed(self, spec: ModelSpec, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(model=spec.model, input=texts)
        return [item.embedding for item in sorted(response.data, key=lambda d: d.index)]


class AnthropicBackend:
    def __init__(self, http_client: httpx2.AsyncClient | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(
            max_retries=0, timeout=REQUEST_TIMEOUT_S, http_client=http_client
        )

    async def chat(
        self,
        spec: ModelSpec,
        messages: list[Message],
        *,
        system_prompt: str | None,
        tools: list[ToolSpec] | None,
        json_schema: dict[str, Any] | None,
        temperature: float,  # anthropic 2.x takes no sampling parameters; only caching uses it
        seed: int | None,  # and no seed
    ) -> TargetReply:
        system_parts = [system_prompt] if system_prompt else []
        system_parts += [m.content for m in messages if m.role == "system"]
        wire: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                continue
            if message.role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
                wire.append({"role": "user", "content": [block]})
            else:
                wire.append({"role": message.role, "content": message.content})
        kwargs: dict[str, Any] = {}
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)
        if json_schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
        if tools:
            kwargs["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters or {"type": "object", "properties": {}},
                }
                for tool in tools
            ]
        started = time.perf_counter()
        response = await self._client.messages.create(
            model=spec.model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            messages=cast(list[MessageParam], wire),
            **kwargs,
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
        text = "".join(block.text for block in response.content if block.type == "text")
        schemas = {tool.name: tool.parameters for tool in tools or []}
        calls = [
            ToolCall(
                id=block.id,
                name=block.name,
                arguments=tool_arguments(json.dumps(block.input), schemas.get(block.name)),
            )
            for block in response.content
            if block.type == "tool_use"
        ]
        return TargetReply(content=text, tool_calls=calls, latency_ms=latency_ms)

    async def embed(self, spec: ModelSpec, texts: list[str]) -> list[list[float]]:
        raise ValueError("Anthropic has no embeddings endpoint; use an Ollama or OpenAI model")


# The client


class EmbeddingClient(Protocol):
    async def embed(
        self, texts: list[str], *, model: str = "nomic-embed-text"
    ) -> list[list[float]]: ...


class LLMClient(EmbeddingClient, Protocol):
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


T = TypeVar("T")


class RateLimitedLLMClient:
    def __init__(
        self,
        cache: ResponseCache | None = None,
        limits: Limits = Limits(),
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        """`http_client` replaces the SDKs' transport. Both SDKs use httpx2, not httpx, so
        respx can't intercept them: tests pass an httpx2 client with a MockTransport."""
        self.cache = cache
        self._http_client = http_client
        self.limits = limits
        self.local = Lane(limits.local_concurrency)
        self.remote = Lane(
            limits.remote_concurrency, SlidingWindow(limits.remote_per_minute, sleep=sleep)
        )
        self._sleep = sleep
        self._backends: dict[tuple[str, str | None], Backend] = {}

    def backend(self, spec: ModelSpec) -> Backend:
        key = (spec.provider, spec.base_url)
        if key not in self._backends:
            http = self._http_client
            if spec.provider == "anthropic":
                self._backends[key] = AnthropicBackend(http)
            elif spec.provider == "ollama":
                self._backends[key] = OpenAIBackend(
                    spec.base_url, "ollama", OLLAMA_EXTRA_BODY, http
                )
            elif spec.provider == "openai":
                self._backends[key] = OpenAIBackend(None, None, None, http)
            else:
                api_key = os.environ.get("OPENAI_API_KEY", "not-needed")
                self._backends[key] = OpenAIBackend(spec.base_url, api_key, None, http)
        return self._backends[key]

    async def _call(self, spec: ModelSpec, call: Callable[[], Awaitable[T]]) -> T:
        if spec.is_local:
            async with self.local.slot():
                return await call()
        attempt = 0
        while True:
            try:
                async with self.remote.slot():
                    return await call()
            except Exception as exc:
                if not is_retryable(exc) or attempt >= self.limits.max_retries:
                    raise
                ceiling = min(self.limits.backoff_cap_s, self.limits.backoff_base_s * 2**attempt)
                await self._sleep(_retry_after(exc) or random.uniform(0, ceiling))
                attempt += 1

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
    ) -> TargetReply:
        spec = parse_model_spec(model_spec)
        key = None
        if self.cache is not None and temperature == 0.0:
            key = cache_key(
                model_spec,
                messages,
                system_prompt=system_prompt,
                tools=tools,
                json_schema=json_schema,
                temperature=temperature,
                seed=seed,
            )
            cached = await self.cache.get(key)
            if cached is not None:
                return cached
        backend = self.backend(spec)
        reply = await self._call(
            spec,
            lambda: backend.chat(
                spec,
                messages,
                system_prompt=system_prompt,
                tools=tools,
                json_schema=json_schema,
                temperature=temperature,
                seed=seed,
            ),
        )
        if key is not None and self.cache is not None:
            await self.cache.put(key, reply)
        return reply

    async def embed(
        self, texts: list[str], *, model: str = "nomic-embed-text"
    ) -> list[list[float]]:
        spec = parse_model_spec(model)
        backend = self.backend(spec)
        return await self._call(spec, lambda: backend.embed(spec, texts))


_default: RateLimitedLLMClient | None = None


def default_client() -> RateLimitedLLMClient:
    """The process-wide client. Use it unless a test hands you another one."""
    global _default
    if _default is None:
        _default = RateLimitedLLMClient()
    return _default


def set_default_client(client: RateLimitedLLMClient) -> None:
    """Swap the process-wide client, for example to attach the store's cache (#7)."""
    global _default
    _default = client
