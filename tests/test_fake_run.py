import importlib.util
from pathlib import Path
from types import ModuleType

from wonderland_court.contracts import (
    AttackSent,
    MatchEnded,
    MatchStarted,
    ReplyReceived,
    Ruling,
    RunEnded,
    RunStarted,
    VerdictRuled,
    read_events,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "fake_run.jsonl"
EVENTS = list(read_events(FIXTURE))


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "make_fake_run", ROOT / "scripts" / "make_fake_run.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_is_up_to_date_with_the_script() -> None:
    expected = load_script().render()
    assert FIXTURE.read_text(encoding="utf-8") == expected, (
        "fixtures/fake_run.jsonl is stale: run `uv run python scripts/make_fake_run.py`"
    )


def test_run_is_bracketed_and_ordered() -> None:
    assert isinstance(EVENTS[0], RunStarted)
    assert isinstance(EVENTS[-1], RunEnded)
    assert [e.seq for e in EVENTS] == list(range(len(EVENTS)))
    assert all(a.ts <= b.ts for a, b in zip(EVENTS, EVENTS[1:], strict=False))
    assert {e.run_id for e in EVENTS} == {EVENTS[0].run_id}


def test_turns_belong_to_started_matches_and_follow_attack_reply_verdict() -> None:
    started: set[str] = set()
    expected = ("attack", "reply", "verdict")
    step: dict[str, int] = {}
    for event in EVENTS:
        if isinstance(event, MatchStarted):
            started.add(event.match.match_id)
            step[event.match.match_id] = 0
        elif isinstance(event, AttackSent | ReplyReceived | VerdictRuled):
            assert event.match_id in started
            assert event.type == expected[step[event.match_id] % 3]
            assert event.turn == step[event.match_id] // 3 + 1
            step[event.match_id] += 1


def test_match_results_agree_with_verdicts() -> None:
    first_leak: dict[str, int] = {}
    for event in EVENTS:
        if isinstance(event, VerdictRuled) and event.verdict.ruling is Ruling.LEAK:
            first_leak.setdefault(event.match_id, event.turn)
    ended = [e for e in EVENTS if isinstance(e, MatchEnded)]
    for match in ended:
        assert match.broken == (match.match_id in first_leak)
        assert match.broken_on_turn == first_leak.get(match.match_id)
    run_end = EVENTS[-1]
    assert isinstance(run_end, RunEnded)
    assert run_end.matches == len(ended)
    assert run_end.leaks == len(first_leak)
