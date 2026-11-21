"""Issue #55: the Cheshire Cat plays the Hatter's combo chains and Drink Me's two-turn chain.

No network. The real `RavenFuzzer` and `DrinkMeGenerator` are deterministic per seed.
"""

from __future__ import annotations

import asyncio

from wonderland_court.adversaries.cheshire_cat import CheshireCat
from wonderland_court.adversaries.drink_me import DrinkMeGenerator
from wonderland_court.adversaries.ports import ChainPoisoner, ComboEscalator, Evolver
from wonderland_court.adversaries.raven import RavenFuzzer
from wonderland_court.contracts.models import (
    Attack,
    AttackContext,
    JudgeLayer,
    MatchMode,
    MutatorId,
    Ruling,
    ScenarioId,
    TargetReply,
    TechniqueFamily,
    Turn,
    Verdict,
)

from .fakes import CANARY, make_context
from .test_cheshire_cat import InlineFuzzer, InlinePoisoner


def played(index: int, attack: Attack, *, blocked_by: str | None = None) -> Turn:
    """A turn Alice held. The Queen rules a blocked turn HELD at full confidence, so it is
    never a near-miss and evolution stays out of the way."""
    return Turn(
        index=index,
        attack=attack,
        reply=TargetReply(content="I can't help with that.", blocked_by=blocked_by),
        verdict=Verdict(ruling=Ruling.HELD, layer=JudgeLayer.LLM, confidence=1.0, reason="x"),
    )


def play(cat: CheshireCat, base: AttackContext, blocks: list[str | None]) -> list[Attack]:
    """Play one turn per entry in `blocks`; each entry is the defense that blocks it, if any."""
    history: list[Turn] = []
    attacks: list[Attack] = []
    for turn, blocked_by in enumerate(blocks, start=1):
        context = base.model_copy(update={"turn": turn, "history": list(history)})
        attack = asyncio.run(cat.next_attack(context))
        attacks.append(attack)
        history.append(played(turn, attack, blocked_by=blocked_by))
    return attacks


def authority(**update: object) -> AttackContext:
    """FIXED AUTHORITY on the vault: the family suggests one mutator (homoglyphs)."""
    context = make_context(
        ScenarioId.VAULT, mode=MatchMode.FIXED, family=TechniqueFamily.AUTHORITY.value
    )
    return context.model_copy(update=update)


# Ports


def test_real_helpers_fit_the_optional_ports() -> None:
    assert isinstance(RavenFuzzer(), ComboEscalator)
    assert isinstance(RavenFuzzer(), Evolver)
    assert isinstance(DrinkMeGenerator(), ChainPoisoner)


def test_plain_fuzzer_and_poisoner_lack_the_extras() -> None:
    assert not isinstance(InlineFuzzer(), ComboEscalator)
    assert not isinstance(InlinePoisoner(), ChainPoisoner)


# Combo escalation


def test_blocked_single_mutator_escalates_combo_by_combo() -> None:
    attacks = play(CheshireCat(fuzzer=RavenFuzzer()), authority(), ["guard", "guard", "guard"])
    assert [a.mutators for a in attacks] == [
        ["homoglyphs"],
        ["homoglyphs", "base64"],  # builds on the blocked mutator first
        ["junk_tokens", "caesar"],  # that combo was blocked too: the next one in order
    ]
    assert {a.family for a in attacks} == {TechniqueFamily.AUTHORITY.value}


def test_no_escalation_without_a_block() -> None:
    attacks = play(CheshireCat(fuzzer=RavenFuzzer()), authority(), [None, None])
    assert [a.mutators for a in attacks] == [["homoglyphs"], ["homoglyphs"]]


def test_combos_stay_inside_the_enabled_mutators() -> None:
    enabled = [MutatorId.HOMOGLYPHS, MutatorId.MIXED_LANGUAGE, MutatorId.RIDDLE]
    attacks = play(
        CheshireCat(fuzzer=RavenFuzzer()),
        authority(enabled_mutators=enabled),
        ["guard", "guard", "guard"],
    )
    assert [a.mutators for a in attacks] == [
        ["homoglyphs"],
        ["mixed_language", "riddle"],
        ["homoglyphs"],  # no allowed combo left: back to the family's own mutator
    ]


def test_families_without_suggested_mutators_are_not_escalated() -> None:
    attack = Attack(family="authority", mutators=["homoglyphs"], message="m")
    blocked = played(1, attack, blocked_by="guard")
    context = make_context(
        ScenarioId.VAULT,
        mode=MatchMode.FIXED,
        family=TechniqueFamily.DIRECT_ASK.value,
        turn=2,
        history=[blocked],
    )
    attack = asyncio.run(CheshireCat(fuzzer=RavenFuzzer()).next_attack(context))
    assert attack.mutators == []


def test_plain_fuzzer_keeps_the_suggested_mutators() -> None:
    fuzzer = InlineFuzzer()
    attacks = play(CheshireCat(fuzzer=fuzzer), authority(), ["guard", "guard"])
    assert [a.mutators for a in attacks] == [["homoglyphs"], ["homoglyphs"]]
    assert fuzzer.calls == [["homoglyphs"], ["homoglyphs"]]


def test_combo_escalation_is_deterministic_per_seed() -> None:
    def match(seed: int) -> list[Attack]:
        return play(CheshireCat(fuzzer=RavenFuzzer(), seed=seed), authority(), ["guard"] * 3)

    assert match(4) == match(4)
    assert [a.mutators for a in match(4)] == [a.mutators for a in match(5)]
    assert CANARY not in "".join(a.model_dump_json() for a in match(4))
