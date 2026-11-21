"""court.yaml: what to put on trial and how hard to try.

Precedence, lowest first: field defaults, then the preset, then what court.yaml sets. A preset
passed to `load_config` (as `court trial --quick` will) replaces the file's `preset` key, but
values the file sets still win over the preset's.
"""

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field, ValidationError, field_validator

from wonderland_court.contracts import MatchMode, ScenarioId
from wonderland_court.contracts.models import Contract

PresetName = Literal["first_blood", "quick", "full"]
DEFENSE_PART = re.compile(r"[A-Za-z0-9_.-]+")


class HttpTargetConfig(Contract):
    """A black-box agent behind HTTP. #19 defines the template placeholders and the hooks."""

    kind: Literal["http"]
    url: str
    request_template: dict[str, Any]
    response_path: str = "reply"
    headers: dict[str, str] = {}


class PythonTargetConfig(Contract):
    """A black-box agent as a Python callable, such as `my_pkg.agent:respond`."""

    kind: Literal["python"]
    entrypoint: str


TargetConfig = str | Annotated[HttpTargetConfig | PythonTargetConfig, Field(discriminator="kind")]

PRESETS: dict[str, dict[str, Any]] = {
    "first_blood": {
        "defenses": ["plain"],
        "scenarios": [ScenarioId.VAULT],
        "mode": MatchMode.ADAPTIVE,
        "rounds": 1,
        "max_turns": 4,
    },
    "quick": {
        "defenses": ["plain", "sandwich", "spotlighting", "spotlighting+guard+output_filter"],
        "scenarios": [ScenarioId.VAULT, ScenarioId.REFUND_TOOL],
        "mode": MatchMode.ADAPTIVE,
        "rounds": 1,
        "max_turns": 3,
    },
    "full": {
        "defenses": [
            "plain",
            "sandwich",
            "input_filter",
            "output_filter",
            "guard",
            "spotlighting",
            "dual_llm",
            "spotlighting+guard+output_filter",
        ],
        "scenarios": [
            ScenarioId.VAULT,
            ScenarioId.SYSTEM_PROMPT,
            ScenarioId.REFUND_TOOL,
            ScenarioId.DRINK_ME,
        ],
        "mode": MatchMode.ADAPTIVE,
        "rounds": 3,
        "max_turns": 6,
    },
}


class CourtConfig(Contract):
    target: TargetConfig
    """`ollama:llama3.1`, `openai:<model>`, `anthropic:<model>`, `python:pkg.mod:fn`, or a dict."""
    preset: PresetName = "quick"
    defenses: list[str] = Field(min_length=1)
    """Defense names, or stacks joined with `+`."""
    scenarios: list[ScenarioId] = Field(min_length=1)
    mode: MatchMode
    rounds: int = Field(ge=1)
    max_turns: int = Field(ge=1)
    seed: int = 1865
    attacker_model: str = "qwen3.5:4b"
    judge_model: str = "llama3.1"
    guard_model: str = "llama-guard3:1b"
    """The `guard` defense's classifier: a Llama Guard 3 or Granite Guardian model."""
    quarantine_model: str | None = None
    """The model `dual_llm` reads untrusted text with. Unset means the target's own model."""
    embed_model: str = "nomic-embed-text"
    db_path: Path = Path(".court/court.db")

    @field_validator("defenses")
    @classmethod
    def _check_defenses(cls, defenses: list[str]) -> list[str]:
        for defense in defenses:
            if not all(DEFENSE_PART.fullmatch(part) for part in defense.split("+")):
                raise ValueError(f"bad defense name {defense!r}")
        if len(set(defenses)) != len(defenses):
            raise ValueError("each defense can only be listed once")
        return defenses

    @field_validator("scenarios")
    @classmethod
    def _check_scenarios(cls, scenarios: list[ScenarioId]) -> list[ScenarioId]:
        if len(set(scenarios)) != len(scenarios):
            raise ValueError("each scenario can only be listed once")
        return scenarios

    @classmethod
    def from_mapping(cls, data: dict[str, Any], preset: PresetName | None = None) -> "CourtConfig":
        chosen = preset or data.get("preset", "quick")
        if chosen not in PRESETS:
            raise ValueError(f"unknown preset {chosen!r}; pick one of {', '.join(PRESETS)}")
        return cls.model_validate({**PRESETS[chosen], **data, "preset": chosen})


class ConfigError(ValueError):
    pass


def load_config(path: Path, preset: PresetName | None = None) -> CourtConfig:
    """Read court.yaml. A relative `db_path` is resolved against the file's directory."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"can't read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} should be a mapping of settings, not {type(data).__name__}")
    try:
        config = CourtConfig.from_mapping(data, preset)
    except (ValidationError, ValueError) as exc:
        raise ConfigError(f"{path} is invalid:\n{exc}") from exc
    if not config.db_path.is_absolute():
        config = config.model_copy(update={"db_path": path.parent / config.db_path})
    return config
