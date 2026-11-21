"""Rebuild matches from a run's event stream.

The Caterpillar and judge calibration read finished runs. Until the Engine's `CourtStore`
(#7) lands they read the JSON-lines event stream instead (`read_events`), which carries the
same data: each match's spec, stakes, turns and outcome.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from wonderland_court.contracts.events import (
    AttackSent,
    Event,
    MatchEnded,
    MatchStarted,
    ReplyReceived,
    VerdictRuled,
    read_events,
)
from wonderland_court.contracts.models import (
    Attack,
    MatchSpec,
    Stakes,
    TargetReply,
    Turn,
    Verdict,
)


@dataclass
class MatchRecord:
    """One match as it happened. `turns` holds only turns with an attack, reply and verdict."""

    run_id: str
    match: MatchSpec
    stakes: Stakes
    turns: list[Turn] = field(default_factory=list)
    ended: MatchEnded | None = None

    @property
    def broken(self) -> bool:
        return self.ended is not None and self.ended.broken


@dataclass
class _Partial:
    attack: Attack | None = None
    reply: TargetReply | None = None
    verdict: Verdict | None = None


def matches_from_events(events: Iterable[Event]) -> list[MatchRecord]:
    """Group events into matches, in the order the matches started.

    Events for a match id that never started are ignored. Turns missing an attack, reply or
    verdict (an interrupted run) are dropped.
    """
    records: dict[str, MatchRecord] = {}
    partial: dict[tuple[str, int], _Partial] = {}
    for event in events:
        if isinstance(event, MatchStarted):
            records[event.match.match_id] = MatchRecord(event.run_id, event.match, event.stakes)
        elif isinstance(event, AttackSent):
            partial.setdefault((event.match_id, event.turn), _Partial()).attack = event.attack
        elif isinstance(event, ReplyReceived):
            partial.setdefault((event.match_id, event.turn), _Partial()).reply = event.reply
        elif isinstance(event, VerdictRuled):
            partial.setdefault((event.match_id, event.turn), _Partial()).verdict = event.verdict
        elif isinstance(event, MatchEnded) and event.match_id in records:
            records[event.match_id].ended = event
    for (match_id, turn), p in sorted(partial.items(), key=lambda kv: kv[0]):
        record = records.get(match_id)
        if record and p.attack and p.reply and p.verdict:
            record.turns.append(Turn(index=turn, attack=p.attack, reply=p.reply, verdict=p.verdict))
    return list(records.values())


def load_matches(path: Path) -> list[MatchRecord]:
    """`matches_from_events` over a JSON-lines event file."""
    return matches_from_events(read_events(path))
