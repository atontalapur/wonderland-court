"""Seeded multi-armed bandit over the Cheshire Cat's technique families.

Arm statistics are rebuilt from `AttackContext.history` on every call, so the
bandit holds no state between turns or matches. The arm-picking rule is a
`SelectionPolicy`; UCB1 is the default, and other policies (Thompson sampling,
warm-started priors) plug in without changing `TechniqueBandit`.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from wonderland_court.contracts.models import Ruling, TechniqueFamily, Turn

NEAR_MISS_CONFIDENCE = 0.75
NEAR_MISS_REWARD = 0.4


@dataclass
class ArmStats:
    pulls: int = 0
    total_reward: float = 0.0
    last_blocked_turn: int | None = None

    @property
    def mean(self) -> float:
        return self.total_reward / self.pulls if self.pulls else 0.0


def turn_reward(turn: Turn) -> float:
    """LEAK is 1.0, a blocked turn 0.0, a low-confidence HELD 0.4, any other HELD 0.0."""
    if turn.verdict.ruling is Ruling.LEAK:
        return 1.0
    if turn.reply.blocked_by is not None:
        return 0.0
    if turn.verdict.confidence < NEAR_MISS_CONFIDENCE:
        return NEAR_MISS_REWARD
    return 0.0


def arm_stats(
    arms: Sequence[TechniqueFamily], history: Sequence[Turn]
) -> dict[TechniqueFamily, ArmStats]:
    """Per-arm pulls, rewards and last blocked turn. Turns for other families are ignored."""
    stats = {arm: ArmStats() for arm in arms}
    by_value = {arm.value: arm for arm in arms}
    for turn in history:
        arm = by_value.get(turn.attack.family)
        if arm is None:
            continue
        entry = stats[arm]
        entry.pulls += 1
        entry.total_reward += turn_reward(turn)
        if turn.reply.blocked_by is not None:
            entry.last_blocked_turn = turn.index
    return stats


class SelectionPolicy(Protocol):
    """Picks one arm from `candidates`, given stats over every arm."""

    def choose(
        self,
        candidates: Sequence[TechniqueFamily],
        stats: Mapping[TechniqueFamily, ArmStats],
        rng: random.Random,
    ) -> TechniqueFamily: ...


@dataclass(frozen=True)
class UCB1Policy:
    """UCB1: untried arms first, then the highest mean plus exploration bonus.

    Ties break with `rng`, so the same seed gives the same pick.
    """

    exploration: float = math.sqrt(2)

    def choose(
        self,
        candidates: Sequence[TechniqueFamily],
        stats: Mapping[TechniqueFamily, ArmStats],
        rng: random.Random,
    ) -> TechniqueFamily:
        untried = [arm for arm in candidates if stats[arm].pulls == 0]
        if untried:
            return rng.choice(untried)
        total = sum(entry.pulls for entry in stats.values())
        log_total = math.log(max(total, 1))

        def score(arm: TechniqueFamily) -> float:
            entry = stats[arm]
            return entry.mean + self.exploration * math.sqrt(log_total / entry.pulls)

        best = max(score(arm) for arm in candidates)
        tied = [arm for arm in candidates if math.isclose(score(arm), best)]
        return rng.choice(tied)


class TechniqueBandit:
    """Chooses the next technique family from the match history.

    An arm blocked by a defense sits out the next `cooldown_turns` turns, unless
    every arm is cooling down. `preferred` arms win when they are untried, which
    lets the Cat steer its opener and its pivots per scenario.
    """

    def __init__(self, *, policy: SelectionPolicy | None = None, cooldown_turns: int = 1) -> None:
        self.policy: SelectionPolicy = policy or UCB1Policy()
        self.cooldown_turns = cooldown_turns

    def select(
        self,
        arms: Sequence[TechniqueFamily],
        history: Sequence[Turn],
        rng: random.Random,
        *,
        turn: int,
        preferred: Sequence[TechniqueFamily] = (),
    ) -> TechniqueFamily:
        if not arms:
            raise ValueError("The bandit needs at least one arm")
        stats = arm_stats(arms, history)
        candidates = [arm for arm in arms if not self.cooling_down(stats[arm], turn)] or list(arms)
        for arm in preferred:
            if arm in candidates and stats[arm].pulls == 0:
                return arm
        return self.policy.choose(candidates, stats, rng)

    def cooling_down(self, stats: ArmStats, turn: int) -> bool:
        blocked = stats.last_blocked_turn
        return blocked is not None and turn - blocked <= self.cooldown_turns
