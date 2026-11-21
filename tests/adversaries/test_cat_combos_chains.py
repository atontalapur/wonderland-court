"""Issue #55: the Cheshire Cat plays the Hatter's combo chains and Drink Me's two-turn chain.

No network. The real `RavenFuzzer` and `DrinkMeGenerator` are deterministic per seed.
"""

from __future__ import annotations

from wonderland_court.adversaries.drink_me import DrinkMeGenerator
from wonderland_court.adversaries.ports import ChainPoisoner, ComboEscalator, Evolver
from wonderland_court.adversaries.raven import RavenFuzzer

from .test_cheshire_cat import InlineFuzzer, InlinePoisoner

# Ports


def test_real_helpers_fit_the_optional_ports() -> None:
    assert isinstance(RavenFuzzer(), ComboEscalator)
    assert isinstance(RavenFuzzer(), Evolver)
    assert isinstance(DrinkMeGenerator(), ChainPoisoner)


def test_plain_fuzzer_and_poisoner_lack_the_extras() -> None:
    assert not isinstance(InlineFuzzer(), ComboEscalator)
    assert not isinstance(InlinePoisoner(), ChainPoisoner)
