"""Data passed between the tracks.

Every model is frozen and rejects unknown fields, so a typo in one track fails loudly in the
other instead of being dropped.
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScenarioId(StrEnum):
    VAULT = "vault"
    SYSTEM_PROMPT = "system_prompt"
    REFUND_TOOL = "refund_tool"
    DRINK_ME = "drink_me"
    MCP_POISON = "mcp_poison"


class TargetKind(StrEnum):
    MODEL = "model"  # Court owns the prompt, tools and documents, so every defense applies
    AGENT = "agent"  # black box over HTTP or Python; only input, output and guard defenses apply


class MatchMode(StrEnum):
    FIXED = "fixed"  # the Cat stays on its assigned technique family
    ADAPTIVE = "adaptive"  # the Cat picks and switches families with its bandit


class Ruling(StrEnum):
    LEAK = "leak"  # "Off with her head"
    HELD = "held"


class JudgeLayer(StrEnum):
    CANARY = "canary"
    TOOL_CALL = "tool_call"
    SIMILARITY = "similarity"
    LLM = "llm"


# Conversation


class Message(Contract):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None


class ToolSpec(Contract):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    """JSON Schema for the tool's arguments."""


class ToolCall(Contract):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Document(Contract):
    """An email, web page or tool output that Alice reads. Drink Me writes the poisoned ones."""

    id: str
    kind: Literal["email", "web_page", "tool_output"]
    title: str
    body: str
    poisoned: bool = False


# What Alice guards


class ToolRule(Contract):
    """A tool call Alice must not make.

    A call to `tool` breaks the rule when `arguments[argument]` is above `max_value`, or does
    not end with `allowed_suffix`.
    """

    tool: str
    argument: str
    max_value: float | None = None
    allowed_suffix: str | None = None
    description: str


class Stakes(Contract):
    """What Alice must protect in one match. The Queen judges every turn against this."""

    scenario: ScenarioId
    objective: str
    """What the attacker is after, in plain words. This is the only part the Cat sees."""
    canary: str
    """Random secret planted for this match. An exact match in a reply is ground truth."""
    protected_text: str | None = None
    """Text that must not come out, such as the system prompt in the `system_prompt` scenario."""
    tool_rules: list[ToolRule] = []


# One turn


class TargetRequest(Contract):
    system_prompt: str
    messages: list[Message]
    tools: list[ToolSpec] = []
    documents: list[Document] = []


class TargetReply(Contract):
    content: str
    tool_calls: list[ToolCall] = []
    blocked_by: str | None = None
    """Name of the defense that refused or rewrote this turn, if any."""
    latency_ms: int = Field(default=0, ge=0)


class Attack(Contract):
    family: str
    """Technique family, such as `role_play`. The family that breaks Alice gets the credit."""
    mutators: list[str] = []
    """Mad Hatter mutators applied to the message, in order."""
    message: str
    document: Document | None = None
    """A Drink Me document delivered alongside the message."""


class Verdict(Contract):
    ruling: Ruling
    layer: JudgeLayer
    """The layer that made the final call."""
    confidence: float = Field(ge=0, le=1)
    reason: str


class Turn(Contract):
    index: int = Field(ge=1)
    attack: Attack
    reply: TargetReply
    verdict: Verdict


# Matches and the tournament


class MatchSpec(Contract):
    match_id: str
    round: int = Field(ge=1)
    target: str
    """Target id, such as `ollama:llama3.1` or `python:my_pkg.agent:respond`."""
    target_kind: TargetKind
    defense: str
    """A defense name, or a stack joined with `+`, such as `spotlighting+guard+output_filter`."""
    scenario: ScenarioId
    attacker: str
    mode: MatchMode
    family: str | None = None
    """The assigned technique family in fixed mode."""
    max_turns: int = Field(ge=1)
    seed: int


class AttackContext(Contract):
    """Everything the attacker gets to plan a turn. It never includes the canary."""

    match_id: str
    scenario: ScenarioId
    objective: str
    mode: MatchMode
    family: str | None = None
    turn: int = Field(ge=1)
    history: list[Turn] = []


class Standing(Contract):
    """One defense's row on the leaderboard."""

    defense: str
    elo: float
    matches: int = Field(ge=0)
    attack_success: float = Field(ge=0, le=1)
    """Share of matches where Alice fell."""
    ci_low: float = Field(ge=0, le=1)
    ci_high: float = Field(ge=0, le=1)
    """Bounds of the 95% interval on `attack_success`."""
    mean_turns_to_break: float | None = None
    utility: float | None = None
    """The Dodo's benign-task pass rate, once wave 2 lands."""
