"""The tournament against a real Ollama server.

Skipped by default (`addopts` deselects the `ollama` marker). Locally:
`OLLAMA_MODEL=qwen3.5:4b uv run pytest -m ollama`.

Uses only `OLLAMA_MODEL`: the scripted attacker and the canary judge make no model calls, and
`plain` and `output_filter` need no guard model. It checks the wiring a mock can't: real
replies reach the board, the registry's Dodo scores a real model, and the final board carries
utility. It doesn't check how well a small model defends itself.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from wonderland_court import registry
from wonderland_court.config import CourtConfig
from wonderland_court.contracts import RunEnded, StandingsUpdated
from wonderland_court.engine.store import CourtStore
from wonderland_court.engine.targets import build_target
from wonderland_court.engine.tournament import run_tournament
from wonderland_court.llm import RateLimitedLLMClient

pytestmark = [pytest.mark.ollama, pytest.mark.asyncio]

MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:0.8b")


async def test_a_one_round_tournament_on_ollama(tmp_path: Path) -> None:
    config = CourtConfig.from_mapping(
        {
            "target": f"ollama:{MODEL}",
            "defenses": ["plain", "output_filter"],
            "scenarios": ["vault"],
            "rounds": 1,
            "max_turns": 2,
            "match_timeout_s": 600,
        }
    )
    client = RateLimitedLLMClient()
    async with CourtStore(tmp_path / "court.db") as store:
        result = await run_tournament(
            config,
            target=build_target(f"ollama:{MODEL}", client),
            attacker=registry.ScriptedAttacker(),
            judge=registry.CanaryJudge(),
            store=store,
            utility=registry.load_utility_evaluator(config, client),
            defense_llm=client,
        )
        events = await store.get_events_after(result.run_id)
        saved = await store.get_utility_results(result.run_id)

    assert result.timed_out == []
    assert len(result.matches) == 2
    assert [e.round for e in events if isinstance(e, StandingsUpdated)] == [1, 1]
    assert isinstance(events[-1], RunEnded) and events[-1].matches == 2
    assert {u.defense for u in saved} == {"plain", "output_filter"}
    for row in result.standings:
        assert row.matches == 1
        assert 0.0 <= row.ci_low <= row.attack_success <= row.ci_high <= 1.0
        assert row.utility is not None and 0.0 <= row.utility <= 1.0
