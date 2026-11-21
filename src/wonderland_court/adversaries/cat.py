"""Registry entry point for the Cheshire Cat: `registry.load_attacker` imports this module."""

from __future__ import annotations

from .cheshire_cat import CheshireCat
from .drink_me import DrinkMeGenerator
from .ports import ChatClient, ModelConfig
from .raven import RavenFuzzer


def build_attacker(*, config: ModelConfig, client: ChatClient) -> CheshireCat:
    """The Cat with the Mad Hatter and Drink Me, refining through `config.attacker_model`."""
    return CheshireCat(
        llm=client,
        fuzzer=RavenFuzzer(),
        poisoner=DrinkMeGenerator(),
        attacker_model=config.attacker_model,
        seed=config.seed,
    )
