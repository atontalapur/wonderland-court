"""Alice as a model target, and `build_target` for every kind of target.

`build_target` sends `python:` specs, http(s) URLs and `court.yaml` target blocks to the agent
adapters in `agent_targets.py`, and everything else here.

Court owns the prompt, tools and documents of a model target, so every defense applies. The
shared LLM client does the network work: it resolves the provider, base URL and API key from
the target id and returns native tool calls already parsed. This module turns a target id into
a `ModelTarget`, renders attached documents into the conversation, recovers tool calls that
local models write as JSON text, and times each call.

Nothing here forces a tool call. Ollama's `/v1` has no `tool_choice`, so no request sets it.
Provider prefixes and tool argument coercion come from `wonderland_court.llm`, so a target id
and a tool call mean the same thing here as they do to the client.
"""

import json
import re
from collections.abc import Iterator, Sequence
from time import perf_counter
from typing import Any, Protocol

from wonderland_court.config import HttpTargetConfig, PythonTargetConfig, TargetConfig
from wonderland_court.contracts import (
    Document,
    Message,
    Target,
    TargetKind,
    TargetReply,
    TargetRequest,
    ToolCall,
    ToolSpec,
)
from wonderland_court.llm import (
    AGENT_PREFIXES,
    PROVIDERS,
    default_client,
    parse_model_spec,
    tool_arguments,
)


class ChatClient(Protocol):
    """The slice of the shared rate-limited LLM client that a model target needs."""

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


# Target ids

_USAGE = (
    "Use ollama:<model> or a bare Ollama model name, openai:<model>, anthropic:<model>, "
    "or openai-compat:<base_url>|<model>."
)
_OLLAMA_MODEL = re.compile(r"[\w./-]+(:[\w.-]+)?")  # name[:tag], such as qwen3.5:4b
_NO_SPACES = re.compile(r"\S+")
_BASE_URL = re.compile(r"https?://\S+")


def canonical_spec(spec: str) -> str:
    """The canonical id of a model target, or a `ValueError` saying what is wrong.

    A spec without a known provider prefix is a bare Ollama model name, so `qwen3.5:4b`
    becomes `ollama:qwen3.5:4b`. HTTP and Python specs are agent targets, which this module
    does not build.
    """
    spec = spec.strip()
    if not spec:
        raise ValueError(f"Empty target spec. {_USAGE}")
    head, _, rest = spec.partition(":")
    prefix = head.lower()
    if prefix in PROVIDERS:
        spec = f"{prefix}:{rest}"

    if prefix in AGENT_PREFIXES:
        raise ValueError(
            f"{spec!r} is an agent target, not a model target. Build it with build_target. {_USAGE}"
        )
    if prefix == "openai-compat":
        base_url, bar, model = rest.partition("|")
        if not (bar and _BASE_URL.fullmatch(base_url) and _NO_SPACES.fullmatch(model)):
            raise ValueError(
                f"{spec!r} should look like openai-compat:<base_url>|<model>, such as "
                "openai-compat:http://localhost:1234/v1|qwen2.5-7b-instruct."
            )
        return parse_model_spec(spec).canonical
    if prefix in ("openai", "anthropic"):
        if not _NO_SPACES.fullmatch(rest):
            raise ValueError(f"{spec!r} has no model name. Expected {prefix}:<model>.")
        return parse_model_spec(spec).canonical

    model = rest if prefix == "ollama" else spec
    if not model:
        raise ValueError(f"{spec!r} has no model name. Expected ollama:<model>.")
    if not _OLLAMA_MODEL.fullmatch(model):
        raise ValueError(f"{spec!r} is not a model target Court knows. {_USAGE}")
    return parse_model_spec(f"ollama:{model}").canonical


# Documents

_KIND_LABELS = {"email": "customer email", "web_page": "web page", "tool_output": "tool output"}


def render_documents(documents: Sequence[Document]) -> str:
    """Documents as delimited attachments, labelled by kind and title.

    They are not marked as trusted or untrusted. Marking them is the spotlighting defense's job.
    """
    blocks = []
    for document in documents:
        label = _KIND_LABELS[document.kind]
        blocks.append(
            f"[Attached {label}: {document.title}]\n{document.body}\n[End of attached {label}]"
        )
    return "\n\n".join(blocks)


def _with_documents(messages: list[Message], documents: list[Document]) -> list[Message]:
    """Append the attachments to the last user turn, or add a user turn if there is none."""
    if not documents:
        return list(messages)
    attachments = render_documents(documents)
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.role == "user":
            content = f"{message.content}\n\n{attachments}" if message.content else attachments
            return [
                *messages[:index],
                message.model_copy(update={"content": content}),
                *messages[index + 1 :],
            ]
    return [*messages, Message(role="user", content=attachments)]


# Tool calls written as text

_JSON_START = re.compile(r"[{\[]")
_DECODER = json.JSONDecoder()


def parse_tool_calls(content: str, tools: Sequence[ToolSpec]) -> list[ToolCall]:
    """Tool calls a model wrote as JSON text instead of native tool calls.

    Local models over Ollama's `/v1` often do this. JSON can sit anywhere in the content, fenced
    or bare, as one call or a list. A call looks like `{"name": ..., "arguments": {...}}`, uses
    `parameters` for the arguments, or is wrapped in `{"function": {...}}`. Only names in
    `tools` count. Arguments are coerced to the tool's schema types, as for native calls, so
    `"amount": "400"` becomes `400.0`. Ids are `call-1`, `call-2` and so on, in order of
    appearance.
    """
    schemas = {tool.name: tool.parameters for tool in tools}
    calls: list[ToolCall] = []
    for value in _json_values(content):
        for name, arguments in calls_in(value):
            if name in schemas:
                coerced = tool_arguments(json.dumps(arguments), schemas[name])
                calls.append(ToolCall(id=f"call-{len(calls) + 1}", name=name, arguments=coerced))
    return calls


def _json_values(text: str) -> Iterator[Any]:
    """Every JSON object or list in the text, scanning left to right."""
    index = 0
    while match := _JSON_START.search(text, index):
        try:
            value, index = _DECODER.raw_decode(text, match.start())
        except json.JSONDecodeError:
            index = match.start() + 1
            continue
        yield value


def calls_in(value: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every `(name, arguments)` tool call in parsed JSON, in order. Agent adapters use it too.

    A call is `{"name": ..., "arguments": {...}}` with `parameters` accepted for the arguments,
    optionally wrapped in `{"function": {...}}`, inside a list or under `"tool_calls"`. String
    arguments are parsed as JSON. Tool definitions echoed back and malformed calls are skipped.
    """
    if isinstance(value, list):
        for item in value:
            yield from calls_in(item)
        return
    if not isinstance(value, dict):
        return
    if isinstance(value.get("tool_calls"), list):
        yield from calls_in(value["tool_calls"])
        return
    if isinstance(value.get("function"), dict):
        value = value["function"]
    name = value.get("name")
    if not isinstance(name, str) or "description" in value:
        return  # not a call, or a tool definition echoed back
    arguments = value.get("arguments", value.get("parameters"))
    if arguments is None:
        arguments = {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return
    if isinstance(arguments, dict):
        yield name, arguments


# The target


class ModelTarget:
    """A model behind the shared LLM client, such as `ollama:llama3.1`."""

    kind = TargetKind.MODEL

    def __init__(
        self,
        spec: str,
        llm: ChatClient | None = None,
        *,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> None:
        self.name = canonical_spec(spec)
        self._llm: ChatClient = llm or default_client()
        self._temperature = temperature
        self._seed = seed

    async def respond(self, request: TargetRequest) -> TargetReply:
        messages = _with_documents(request.messages, request.documents)
        start = perf_counter()
        reply = await self._llm.chat(
            self.name,
            messages,
            system_prompt=request.system_prompt or None,
            tools=request.tools or None,
            temperature=self._temperature,
            seed=self._seed,
        )
        latency_ms = round((perf_counter() - start) * 1000)

        update: dict[str, Any] = {}
        if reply.latency_ms == 0:
            update["latency_ms"] = latency_ms
        if not reply.tool_calls and request.tools:
            calls = parse_tool_calls(reply.content, request.tools)
            if calls:
                update["tool_calls"] = calls
        return reply.model_copy(update=update) if update else reply


def build_target(
    spec: TargetConfig,
    llm: ChatClient | None = None,
    *,
    temperature: float = 0.0,
    seed: int | None = None,
) -> Target:
    """The target for a target id or a `court.yaml` target block.

    `python:<module.path>:<callable>` and a `{kind: python}` block build a Python agent, and an
    http(s) URL or a `{kind: http}` block builds an HTTP agent. Anything else is a model id.
    `llm`, `temperature` and `seed` only apply to model targets: an agent picks its own.
    """
    # agent_targets imports this module, so import it here rather than at the top.
    from .agent_targets import HttpAgentTarget, PythonAgentTarget

    if isinstance(spec, HttpTargetConfig):
        return HttpAgentTarget(spec)
    if isinstance(spec, PythonTargetConfig):
        return PythonAgentTarget(spec.entrypoint)
    spec = spec.strip()
    head, _, rest = spec.partition(":")
    prefix = head.lower()
    if prefix == "python":
        return PythonAgentTarget(rest)
    if prefix in ("http", "https"):
        if not rest.startswith("//"):
            raise ValueError(f"{spec!r} should be a full URL, such as http://localhost:8000/chat.")
        return HttpAgentTarget(HttpTargetConfig(kind="http", url=spec))
    return ModelTarget(spec, llm, temperature=temperature, seed=seed)
