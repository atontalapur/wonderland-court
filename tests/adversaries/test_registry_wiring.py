"""The Engine registry finds the real Adversaries components instead of its fakes."""

from collections.abc import Callable
from typing import Any

import pytest

from wonderland_court import registry
from wonderland_court.adversaries.caterpillar import CaterpillarRemediator
from wonderland_court.adversaries.cheshire_cat import CheshireCat
from wonderland_court.adversaries.dodo import DodoUtility
from wonderland_court.adversaries.judge import QueenJudge
from wonderland_court.config import CourtConfig
from wonderland_court.contracts.models import MatchMode, ScenarioId
from wonderland_court.llm import default_client

CONFIG = CourtConfig(
    target="ollama:llama3.1",
    defenses=["plain"],
    scenarios=[ScenarioId.VAULT],
    mode=MatchMode.ADAPTIVE,
    rounds=1,
    max_turns=3,
)


@pytest.mark.parametrize(
    ("loader", "real_type"),
    [
        (registry.load_attacker, CheshireCat),
        (registry.load_judge, QueenJudge),
        (registry.load_utility_evaluator, DodoUtility),
        (registry.load_remediator, CaterpillarRemediator),
    ],
)
def test_registry_loads_the_real_component(
    loader: Callable[..., Any], real_type: type[Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="wonderland_court.registry"):
        component = loader(CONFIG, default_client())
    assert isinstance(component, real_type)
    assert not getattr(component, "fake", False)
    assert "isn't built yet" not in caplog.text
