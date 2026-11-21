"""Seeded multi-armed bandit over the Cheshire Cat's technique families.

Arm statistics are rebuilt from `AttackContext.history` on every call, so the
bandit holds no state between turns or matches. The arm-picking rule is a
`SelectionPolicy`: `UCB1Policy` (the default) or `ThompsonPolicy`. An optional
warm start adds prior `ArmStats` per family, such as the totals from earlier
matches against the same target and defense.
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
DEFAULT_EXPLORATION = 1.2
"""UCB1 exploration constant, tuned down from sqrt(2) for short 3-6 turn matches."""


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


WarmStart = Mapping[TechniqueFamily, ArmStats]
"""Prior pulls and rewards per family, added to what the match history shows."""


def arm_stats(
    arms: Sequence[TechniqueFamily],
    history: Sequence[Turn],
    *,
    prior: WarmStart | None = None,
) -> dict[TechniqueFamily, ArmStats]:
    """Per-arm pulls, rewards and last blocked turn. Turns for other families are ignored.

    `prior` adds pulls and rewards per arm. Its `last_blocked_turn` is ignored, since turn
    numbers from another match say nothing about cooldowns in this one.
    """
    prior = prior or {}
    stats = {
        arm: ArmStats(pulls=prior[arm].pulls, total_reward=prior[arm].total_reward)
        if arm in prior
        else ArmStats()
        for arm in arms
    }
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

    exploration: float = DEFAULT_EXPLORATION

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


@dataclass(frozen=True)
class ThompsonPolicy:
    """Thompson sampling with a Beta(`prior_alpha`, `prior_beta`) prior per arm.

    A reward in [0, 1] counts as that fraction of a success, so an arm's posterior
    is Beta(alpha + total_reward, beta + pulls - total_reward). Draws come from
    `rng`, so the same seed gives the same pick.
    """

    prior_alpha: float = 1.0
    prior_beta: float = 1.0

    def choose(
        self,
        candidates: Sequence[TechniqueFamily],
        stats: Mapping[TechniqueFamily, ArmStats],
        rng: random.Random,
    ) -> TechniqueFamily:
        if not candidates:
            raise ValueError("ThompsonPolicy needs at least one candidate")

        def draw(arm: TechniqueFamily) -> float:
            entry = stats[arm]
            successes = min(max(entry.total_reward, 0.0), float(entry.pulls))
            failures = entry.pulls - successes
            return rng.betavariate(self.prior_alpha + successes, self.prior_beta + failures)

        draws = [(draw(arm), arm) for arm in candidates]
        return max(draws, key=lambda pair: pair[0])[1]


class TechniqueBandit:
    """Chooses the next technique family from the match history.

    An arm blocked by a defense sits out the next `cooldown_turns` turns, unless
    every arm is cooling down. `preferred` arms win when they are untried, which
    lets the Cat steer its opener and its pivots per scenario.

    `warm_start` adds prior stats per family to every selection. The bandit has no
    idea which target or defense it faces (`AttackContext` carries neither), so the
    caller must pass the warm start that matches the (target, defense) pair of the
    match. An arm with prior pulls no longer counts as untried, so a warm start can
    override the `preferred` opener.
    """

    def __init__(
        self,
        *,
        policy: SelectionPolicy | None = None,
        cooldown_turns: int = 1,
        warm_start: WarmStart | None = None,
    ) -> None:
        self.policy: SelectionPolicy = policy or UCB1Policy()
        self.cooldown_turns = cooldown_turns
        self.warm_start: dict[TechniqueFamily, ArmStats] = dict(warm_start or {})

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
        stats = arm_stats(arms, history, prior=self.warm_start)
        candidates = [arm for arm in arms if not self.cooling_down(stats[arm], turn)] or list(arms)
        for arm in preferred:
            if arm in candidates and stats[arm].pulls == 0:
                return arm
        return self.policy.choose(candidates, stats, rng)

    def cooling_down(self, stats: ArmStats, turn: int) -> bool:
        blocked = stats.last_blocked_turn
        return blocked is not None and turn - blocked <= self.cooldown_turns
