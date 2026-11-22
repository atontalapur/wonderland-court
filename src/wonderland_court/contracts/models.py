"""Data passed between the tracks.

Every model is frozen and rejects unknown fields, so a typo in one track fails loudly in the
other instead of being dropped.
"""

from enum import StrEnum
from importlib.metadata import entry_points
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


SCENARIO_PLUGINS = "wonderland_court.scenarios"
"""The entry point group of scenario plugins. `engine/plugins.py` loads them."""


# The built-in scenarios, plus any scenario an installed plugin adds: `ScenarioId("heist")` is
# valid when an installed package declares a `heist` entry point in `SCENARIO_PLUGINS`. Such an
# id behaves like a built-in one, but iterating `ScenarioId` and the JSON schema list only the
# built-in five. Built-in ids always win. (A comment, not a docstring, so the schema is unchanged.)
class ScenarioId(StrEnum):
    VAULT = "vault"
    SYSTEM_PROMPT = "system_prompt"
    REFUND_TOOL = "refund_tool"
    DRINK_ME = "drink_me"
    MCP_POISON = "mcp_poison"

    @classmethod
    def _missing_(cls, value: object) -> "ScenarioId | None":
        return _plugin_scenario(value)


_PLUGIN_SCENARIOS: dict[str, ScenarioId] = {}


def _plugin_scenario(value: object) -> ScenarioId | None:
    """The id for a scenario plugin's name. Reads package metadata only, and imports nothing."""
    if not isinstance(value, str):
        return None
    if value not in _PLUGIN_SCENARIOS:
        try:
            declared = {point.name for point in entry_points(group=SCENARIO_PLUGINS)}
        except Exception:  # one package's bad metadata must not break validation
            return None
        if value not in declared:
            return None
        member = str.__new__(ScenarioId, value)
        member._name_ = value
        member._value_ = value
        _PLUGIN_SCENARIOS[value] = member
    return _PLUGIN_SCENARIOS[value]


class TargetKind(StrEnum):
    MODEL = "model"  # Court owns the prompt, tools and documents, so every defense applies
    AGENT = "agent"  # black box over HTTP or Python; only input, output and guard defenses apply


class MatchMode(StrEnum):
    FIXED = "fixed"  # the Cat stays on its assigned technique family
    ADAPTIVE = "adaptive"  # the Cat picks and switches families with its bandit


class AdversaryRole(StrEnum):
    """Which Wonderland adversary owns a tactic."""

    CHESHIRE_CAT = "cheshire_cat"
    MAD_HATTER = "mad_hatter"
    DRINK_ME = "drink_me"


class TechniqueFamily(StrEnum):
    """Selectable attack families for the Cheshire Cat (and helpers).

    Demo families keep the fake-run vocabulary. Research families name published
    2024–2026 evaluation methods the Cat can pick as fixed or adaptive tactics.
    """

    # Demo / baseline (already used in fixtures)
    DIRECT_ASK = "direct_ask"
    ROLE_PLAY = "role_play"
    INDIRECT_INJECTION = "indirect_injection"
    AUTHORITY = "authority"
    ENCODING = "encoding"

    # Research-level tactics (2024–2026 papers and lab evals)
    FOOT_IN_THE_DOOR = "foot_in_the_door"
    AUTOADV = "autoadv"
    PAIR = "pair"
    TAP = "tap"
    AGENTDOJO = "agentdojo"
    BIPIA = "bipia"
    RAG_N_ROLL = "rag_n_roll"
    ENCODING_SMUGGLING = "encoding_smuggling"
    MULTILINGUAL = "multilingual"
    MCP_TOOL_POISONING = "mcp_tool_poisoning"
    JAILBREAKBENCH = "jailbreakbench"
    HARMBENCH = "harmbench"
    CAMEL_DUAL_FLOW = "camel_dual_flow"


class MutatorId(StrEnum):
    """Mad Hatter mutators applied on top of a Cat message."""

    HOMOGLYPHS = "homoglyphs"
    SPACED_LETTERS = "spaced_letters"
    BASE64 = "base64"
    CAESAR = "caesar"
    LOW_RESOURCE_LANGUAGE = "low_resource_language"
    MIXED_LANGUAGE = "mixed_language"
    RIDDLE = "riddle"
    JUNK_TOKENS = "junk_tokens"


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
    """Technique family id (see `TechniqueFamily`). The family that breaks Alice gets the credit."""
    mutators: list[str] = []
    """Mad Hatter mutator ids (see `MutatorId`) applied to the message, in order."""
    message: str
    document: Document | None = None
    """A Drink Me document delivered alongside the message."""
    payload: str | None = None
    """The Cat's text before the Hatter mutated it. Set when `mutators` is not empty, so
    evolution can breed from clean text. Alice only ever sees `message`."""


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
    enabled_families: list[TechniqueFamily] | None = None
    """Subset of technique families the Cat may use. `None` means the full default catalog."""
    enabled_mutators: list[MutatorId] | None = None
    """Subset of Mad Hatter mutators allowed this match. `None` means the full default set."""
    max_turns: int = Field(ge=1)
    seed: int


class AttackContext(Contract):
    """Everything the attacker gets to plan a turn. It never includes the canary."""

    match_id: str
    scenario: ScenarioId
    objective: str
    mode: MatchMode
    family: str | None = None
    enabled_families: list[TechniqueFamily] | None = None
    """Selectable families for this turn. `None` means the full default catalog."""
    enabled_mutators: list[MutatorId] | None = None
    """Selectable Mad Hatter mutators for this turn. `None` means the full default set."""
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
