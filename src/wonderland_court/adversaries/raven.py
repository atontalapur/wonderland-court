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
