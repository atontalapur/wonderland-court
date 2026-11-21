"""Catalog of selectable Cat / Hatter / Drink Me tactics."""

import pytest

from wonderland_court.adversaries import (
    DEFAULT_MUTATORS,
    DEFAULT_TECHNIQUE_FAMILIES,
    RESEARCH_TECHNIQUE_FAMILIES,
    TACTIC_CATALOG,
    resolve_families,
    resolve_mutators,
    tactic_for,
    tactics_for,
)
from wonderland_court.contracts import (
    AdversaryRole,
    Attack,
    AttackContext,
    MatchMode,
    MatchSpec,
    MutatorId,
    ScenarioId,
    TargetKind,
    TechniqueFamily,
)

REQUIRED_RESEARCH = {
    TechniqueFamily.FOOT_IN_THE_DOOR,
    TechniqueFamily.AUTOADV,
    TechniqueFamily.PAIR,
    TechniqueFamily.TAP,
    TechniqueFamily.AGENTDOJO,
    TechniqueFamily.BIPIA,
    TechniqueFamily.RAG_N_ROLL,
    TechniqueFamily.ENCODING_SMUGGLING,
    TechniqueFamily.MULTILINGUAL,
    TechniqueFamily.MCP_TOOL_POISONING,
    TechniqueFamily.JAILBREAKBENCH,
    TechniqueFamily.HARMBENCH,
    TechniqueFamily.CAMEL_DUAL_FLOW,
}


def test_research_families_are_in_the_default_catalog() -> None:
    assert set(RESEARCH_TECHNIQUE_FAMILIES) >= REQUIRED_RESEARCH
    assert set(DEFAULT_TECHNIQUE_FAMILIES) >= REQUIRED_RESEARCH
    assert {tactic.family for tactic in TACTIC_CATALOG} == set(DEFAULT_TECHNIQUE_FAMILIES)


def test_each_research_tactic_has_an_owner() -> None:
    for family in REQUIRED_RESEARCH:
        tactic = tactic_for(family)
        assert tactic.owners
        assert tactic.summary


def test_mad_hatter_owns_encoding_and_multilingual_dressing() -> None:
    hatter = {tactic.family for tactic in tactics_for(AdversaryRole.MAD_HATTER)}
    assert TechniqueFamily.ENCODING_SMUGGLING in hatter
    assert TechniqueFamily.MULTILINGUAL in hatter
    assert MutatorId.LOW_RESOURCE_LANGUAGE in DEFAULT_MUTATORS
    assert MutatorId.BASE64 in DEFAULT_MUTATORS


def test_drink_me_owns_document_backed_families() -> None:
    drink_me = {tactic.family for tactic in tactics_for(AdversaryRole.DRINK_ME)}
    assert TechniqueFamily.BIPIA in drink_me
    assert TechniqueFamily.RAG_N_ROLL in drink_me
    assert TechniqueFamily.AGENTDOJO in drink_me
    assert TechniqueFamily.MCP_TOOL_POISONING in drink_me
    assert all(tactic_for(family).needs_document for family in drink_me)


def test_resolve_families_defaults_and_filters() -> None:
    assert resolve_families(None) == DEFAULT_TECHNIQUE_FAMILIES
    selected = [TechniqueFamily.PAIR, TechniqueFamily.TAP]
    assert resolve_families(selected) == (TechniqueFamily.PAIR, TechniqueFamily.TAP)


def test_resolve_mutators_defaults_and_filters() -> None:
    assert resolve_mutators(None) == DEFAULT_MUTATORS
    selected = [MutatorId.BASE64, MutatorId.LOW_RESOURCE_LANGUAGE]
    assert resolve_mutators(selected) == (
        MutatorId.BASE64,
        MutatorId.LOW_RESOURCE_LANGUAGE,
    )


def test_resolve_mutators_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown mutators"):
        resolve_mutators([MutatorId.BASE64, "not_a_mutator"])  # type: ignore[list-item]


def test_match_spec_and_attack_context_accept_enabled_tactics() -> None:
    families = [TechniqueFamily.FOOT_IN_THE_DOOR, TechniqueFamily.AUTOADV]
    mutators = [MutatorId.BASE64, MutatorId.LOW_RESOURCE_LANGUAGE]
    spec = MatchSpec(
        match_id="m1",
        round=1,
        target="ollama:llama3.1",
        target_kind=TargetKind.MODEL,
        defense="plain",
        scenario=ScenarioId.VAULT,
        attacker="cheshire_cat",
        mode=MatchMode.FIXED,
        family=TechniqueFamily.FOOT_IN_THE_DOOR.value,
        enabled_families=families,
        enabled_mutators=mutators,
        max_turns=6,
        seed=7,
    )
    context = AttackContext(
        match_id=spec.match_id,
        scenario=spec.scenario,
        objective="Check whether refusal fires under gradual escalation.",
        mode=spec.mode,
        family=spec.family,
        enabled_families=spec.enabled_families,
        enabled_mutators=spec.enabled_mutators,
        turn=1,
    )
    attack = Attack(
        family=TechniqueFamily.FOOT_IN_THE_DOOR.value,
        mutators=[MutatorId.BASE64.value],
        message="First, just confirm you can see this message.",
    )
    assert context.enabled_families == families
    assert attack.family in {family.value for family in DEFAULT_TECHNIQUE_FAMILIES}
