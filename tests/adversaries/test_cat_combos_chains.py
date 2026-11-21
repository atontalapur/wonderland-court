"""Issue #55: the Cheshire Cat plays the Hatter's combo chains and Drink Me's two-turn chain.

No network. The real `RavenFuzzer` and `DrinkMeGenerator` are deterministic per seed.
"""

from __future__ import annotations

import asyncio
import json

import pytest

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


# Chained Drink Me


def drink_me(scenario: ScenarioId = ScenarioId.REFUND_TOOL) -> AttackContext:
    """ADAPTIVE with only INDIRECT_INJECTION enabled, so every turn is a document turn."""
    return make_context(scenario).model_copy(
        update={"enabled_families": [TechniqueFamily.INDIRECT_INJECTION]}
    )


def test_two_turn_chain_on_refund_tool() -> None:
    attacks = play(CheshireCat(poisoner=DrinkMeGenerator()), drink_me(), [None, None])
    setup, payload = (a.document for a in attacks)
    assert setup is not None and payload is not None
    assert setup.kind == "email" and not setup.poisoned
    assert payload.kind == "tool_output" and payload.poisoned
    record = json.loads(payload.body)
    assert record["interaction_history"][0]["ref"] == setup.id
    assert f"#{record['order_id']}" in setup.body
    assert {a.family for a in attacks} == {TechniqueFamily.INDIRECT_INJECTION.value}


@pytest.mark.parametrize("scenario", [ScenarioId.REFUND_TOOL, ScenarioId.DRINK_ME])
def test_chain_keeps_its_family_for_the_payload(scenario: ScenarioId) -> None:
    # Every family is enabled: role play opens, the refusal pivots to Drink Me, and the
    # payload turn stays on that family instead of going back to the bandit.
    attacks = play(CheshireCat(poisoner=DrinkMeGenerator()), make_context(scenario), [None] * 3)
    assert [a.family for a in attacks] == ["role_play", "indirect_injection", "indirect_injection"]
    assert attacks[0].document is None
    setup, payload = attacks[1].document, attacks[2].document
    assert setup is not None and not setup.poisoned
    assert payload is not None and payload.poisoned
    assert json.loads(payload.body)["interaction_history"][0]["ref"] == setup.id


def test_a_new_chain_starts_after_the_payload() -> None:
    attacks = play(CheshireCat(poisoner=DrinkMeGenerator()), drink_me(), [None] * 4)
    documents = [a.document for a in attacks if a.document is not None]
    assert [d.poisoned for d in documents] == [False, True, False, True]
    first_setup, first_payload, second_setup, second_payload = documents
    assert second_setup.id != first_setup.id
    for setup, payload in ((first_setup, first_payload), (second_setup, second_payload)):
        assert json.loads(payload.body)["interaction_history"][0]["ref"] == setup.id


@pytest.mark.parametrize(
    ("poisoner", "context"),
    [
        (
            DrinkMeGenerator(),
            make_context(
                ScenarioId.REFUND_TOOL,
                mode=MatchMode.FIXED,
                family=TechniqueFamily.INDIRECT_INJECTION.value,
            ),
        ),
        (DrinkMeGenerator(), drink_me(ScenarioId.VAULT)),
        (InlinePoisoner(), drink_me()),
    ],
    ids=["fixed-mode", "vault", "plain-poisoner"],
)
def test_no_chain_outside_adaptive_tea_shop_matches(
    poisoner: DrinkMeGenerator | InlinePoisoner, context: AttackContext
) -> None:
    attacks = play(CheshireCat(poisoner=poisoner), context, [None, None])
    assert all(a.document is not None and a.document.poisoned for a in attacks)
    assert {a.family for a in attacks} == {TechniqueFamily.INDIRECT_INJECTION.value}


def test_chain_is_deterministic_per_seed() -> None:
    def match(seed: int) -> list[Attack]:
        cat = CheshireCat(fuzzer=RavenFuzzer(), poisoner=DrinkMeGenerator(), seed=seed)
        return play(cat, drink_me(), [None] * 3)

    assert match(2) == match(2)
    first, other = match(2)[0].document, match(3)[0].document
    assert first is not None and other is not None and first.id != other.id
    assert CANARY not in "".join(a.model_dump_json() for a in match(2))
