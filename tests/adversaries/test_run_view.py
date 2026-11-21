from pathlib import Path

from wonderland_court.adversaries.run_view import load_matches, matches_from_events
from wonderland_court.contracts.events import MatchStarted, VerdictRuled, read_events

FAKE_RUN = Path(__file__).resolve().parents[2] / "fixtures" / "fake_run.jsonl"


def test_fake_run_rebuilds_into_matches() -> None:
    records = load_matches(FAKE_RUN)
    assert len(records) == 8
    for record in records:
        assert record.ended is not None
        assert [t.index for t in record.turns] == list(range(1, record.ended.turns + 1))
        if record.broken:
            last = record.turns[-1]
            assert last.verdict.ruling == "leak"
            assert record.ended.breaking_family == last.attack.family


def test_incomplete_turns_and_unknown_matches_are_dropped() -> None:
    events = list(read_events(FAKE_RUN))
    # Drop the first verdict: its turn can't be rebuilt, the rest of the match still can.
    first_verdict = next(i for i, e in enumerate(events) if isinstance(e, VerdictRuled))
    verdict = events[first_verdict]
    assert isinstance(verdict, VerdictRuled)
    match_id = verdict.match_id
    trimmed = events[:first_verdict] + events[first_verdict + 1 :]
    records = {r.match.match_id: r for r in matches_from_events(trimmed)}
    assert 1 not in [t.index for t in records[match_id].turns]
    # Without its match_started event a match disappears entirely.
    no_start = [
        e for e in events if not (isinstance(e, MatchStarted) and e.match.match_id == match_id)
    ]
    assert match_id not in {r.match.match_id for r in matches_from_events(no_start)}
