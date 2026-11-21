"""The event stream.

The engine emits these, the store records them as JSON lines, and the Courtroom reads the same
JSON over its live stream and in replay mode. One event per line, ordered by `seq`.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import AwareDatetime, Field, TypeAdapter

from .models import (
    Attack,
    Contract,
    MatchMode,
    MatchSpec,
    ScenarioId,
    Stakes,
    Standing,
    TargetReply,
    Verdict,
)

SCHEMA_VERSION: Final = 1


class EventBase(Contract):
    v: Literal[1] = SCHEMA_VERSION
    seq: int = Field(ge=0)
    ts: AwareDatetime
    run_id: str


class RunStarted(EventBase):
    type: Literal["run_started"] = "run_started"
    targets: list[str]
    defenses: list[str]
    scenarios: list[ScenarioId]
    mode: MatchMode
    rounds: int = Field(ge=1)


class MatchStarted(EventBase):
    type: Literal["match_started"] = "match_started"
    match: MatchSpec
    stakes: Stakes


class AttackSent(EventBase):
    """The Cat's move. Sent before Alice answers, so the Courtroom can show it while she thinks."""

    type: Literal["attack"] = "attack"
    match_id: str
    turn: int = Field(ge=1)
    attack: Attack


class ReplyReceived(EventBase):
    type: Literal["reply"] = "reply"
    match_id: str
    turn: int = Field(ge=1)
    reply: TargetReply


class VerdictRuled(EventBase):
    type: Literal["verdict"] = "verdict"
    match_id: str
    turn: int = Field(ge=1)
    verdict: Verdict


class MatchEnded(EventBase):
    type: Literal["match_ended"] = "match_ended"
    match_id: str
    broken: bool
    turns: int = Field(ge=0)
    broken_on_turn: int | None = None
    breaking_family: str | None = None


class StandingsUpdated(EventBase):
    type: Literal["standings"] = "standings"
    round: int = Field(ge=1)
    standings: list[Standing]


class RunEnded(EventBase):
    type: Literal["run_ended"] = "run_ended"
    matches: int = Field(ge=0)
    leaks: int = Field(ge=0)


Event = Annotated[
    RunStarted
    | MatchStarted
    | AttackSent
    | ReplyReceived
    | VerdictRuled
    | MatchEnded
    | StandingsUpdated
    | RunEnded,
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


def parse_event(line: str | bytes) -> Event:
    return EVENT_ADAPTER.validate_json(line)


def dump_event(event: Event) -> str:
    return event.model_dump_json()


def read_events(path: Path) -> Iterator[Event]:
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            if line.strip():
                yield parse_event(line)


def event_json_schema() -> dict[str, Any]:
    """JSON Schema for one event line. The Courtroom can generate its TypeScript types from it."""
    return EVENT_ADAPTER.json_schema()
