"""The Mad Hatter's fuzzer: picks mutators by seed and chains them over a Cat payload.

`RavenFuzzer` fits `ports.Fuzzer`. Its output plugs straight into
`Attack(mutators=applied, message=mutated)`. `evolve_from_history` breeds a payload from a
match's near-miss turns (see `evolution`).
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import cast

from wonderland_court.adversaries.evolution import PayloadEvolver
from wonderland_court.adversaries.mutators import MUTATOR_REGISTRY, WRAPPING_MUTATORS
from wonderland_court.adversaries.ports import Mutator
from wonderland_court.adversaries.tactics import resolve_mutators
from wonderland_court.contracts.models import MutatorId, Turn

COMBO_CHAINS: tuple[tuple[MutatorId, MutatorId], ...] = (
    (MutatorId.HOMOGLYPHS, MutatorId.BASE64),
    (MutatorId.JUNK_TOKENS, MutatorId.CAESAR),
    (MutatorId.MIXED_LANGUAGE, MutatorId.RIDDLE),
    (MutatorId.SPACED_LETTERS, MutatorId.LOW_RESOURCE_LANGUAGE),
)
"""Curated two-step pipelines: a surface mutator, then a wrapping one, always in that order.

They stand in for issue #33's chains (zero-width -> markdown smuggling, payload split -> JSON
wrapper, mixed language -> riddle, leetspeak -> whitespace stego), mapped onto the eight
contract mutators. The Hatter escalates to them once single mutators get blocked."""

COMBO_BLOCKERS: frozenset[str] = frozenset({"input_filter", "guard"})
"""Defenses whose blocks on a single mutator trigger the combo escalation."""


class RavenFuzzer:
    """Why is a raven like a writing desk? Both get scrambled by the Hatter."""

    def __init__(self, registry: Mapping[MutatorId, Mutator] = MUTATOR_REGISTRY) -> None:
        self.registry = registry

    def mutate(
        self,
        payload: str,
        *,
        seed: int,
        mutators: list[str] | None = None,
        chain_len: int = 1,
    ) -> tuple[list[str], str]:
        """Apply `chain_len` distinct mutators, picked by seed from `mutators`.

        `mutators` is the pool to pick from; `None` means every registered mutator. The chain
        order is random, except that wrapping mutators (`WRAPPING_MUTATORS`) always run after
        surface ones, so the encoded payload stays decodable.
        Returns the applied mutator ids in order and the mutated payload.

        Raises ValueError for an unknown or unregistered id, or a `chain_len` outside
        1..len(pool).
        """
        pool = self._pool(mutators)
        if not 1 <= chain_len <= len(pool):
            raise ValueError(f"chain_len must be between 1 and {len(pool)}, got {chain_len}")
        rng = random.Random(seed)
        chain = rng.sample(pool, chain_len)
        chain.sort(key=lambda m: m in WRAPPING_MUTATORS)  # stable: keeps the random order
        text = payload
        for mutator_id in chain:
            text = self.registry[mutator_id](text, rng)
        return [m.value for m in chain], text

    def mutate_combo(
        self, payload: str, *, seed: int, combo: tuple[MutatorId, MutatorId]
    ) -> tuple[list[str], str]:
        """Apply one combo chain in its fixed order. Raises ValueError for an unknown combo."""
        if combo not in COMBO_CHAINS:
            raise ValueError(f"Not a curated combo: {' -> '.join(m.value for m in combo)}")
        rng = random.Random(seed)
        text = payload
        for mutator_id in combo:
            text = self.registry[mutator_id](text, rng)
        return [m.value for m in combo], text

    def combo_after_blocks(
        self, history: list[Turn], *, mutators: list[str] | None = None
    ) -> tuple[MutatorId, MutatorId] | None:
        """The combo to escalate to, or None when no single mutator has been blocked.

        Escalation starts once a turn that used exactly one mutator was blocked by
        `input_filter` or `guard`. Combos that build on a blocked mutator come first (it
        gets a second layer of cover), then the rest, in `COMBO_CHAINS` order. Both steps of
        a combo must be in the match's allowed pool, and a combo already tried and blocked
        is skipped.
        """
        blocked_singles = {
            turn.attack.mutators[0]
            for turn in history
            if turn.reply.blocked_by in COMBO_BLOCKERS and len(turn.attack.mutators) == 1
        }
        if not blocked_singles:
            return None
        allowed = {
            MutatorId(m).value for m in resolve_mutators(cast("list[MutatorId]", mutators))
        } & {m.value for m in self.registry}
        tried = {
            tuple(turn.attack.mutators) for turn in history if turn.reply.blocked_by is not None
        }
        usable = [
            combo
            for combo in COMBO_CHAINS
            if {m.value for m in combo} <= allowed and tuple(m.value for m in combo) not in tried
        ]
        building = [c for c in usable if c[0].value in blocked_singles]
        ranked = building + [c for c in usable if c not in building]
        return ranked[0] if ranked else None

    def evolve_from_history(
        self, history: list[Turn], *, seed: int, mutators: list[str] | None = None
    ) -> tuple[list[str], str] | None:
        """Breed a payload from the near-miss turns in `history` with `PayloadEvolver`.

        `mutators` limits the pool to the match's allowed ids. Returns the mutator ids applied
        and the payload, or `None` when no turn is a near-miss.
        """
        return PayloadEvolver(self, seed).evolve(history, mutators=mutators)

    def _pool(self, mutators: list[str] | None) -> list[MutatorId]:
        if mutators is None:
            pool = list(self.registry)
        else:
            # MutatorId is a StrEnum, so resolve_mutators checks plain strings correctly.
            resolved = resolve_mutators(cast("list[MutatorId]", mutators))
            pool = list(dict.fromkeys(MutatorId(m) for m in resolved))
        missing = [m.value for m in pool if m not in self.registry]
        if missing:
            raise ValueError(f"Mutators not registered: {', '.join(missing)}")
        if not pool:
            raise ValueError("No mutators to pick from")
        return pool
