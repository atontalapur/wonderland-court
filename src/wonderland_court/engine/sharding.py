"""Splitting one tournament across laptops.

`court trial --shard k/N` plays the k-th of every N matches in the schedule (`idx % N == k - 1`),
and the k-th of every N Dodo checks. The schedule, match ids and seeds are the same on every
laptop, so the N parts never overlap and together cover the whole tournament.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self, TypeVar

from wonderland_court.config import parse_shard

T = TypeVar("T")


@dataclass(frozen=True)
class Shard:
    """Part `part` of `total`, counting from 1."""

    part: int
    total: int

    def __post_init__(self) -> None:
        if not 1 <= self.part <= self.total:
            raise ValueError(f"shard {self} should be k/N with 1 <= k <= N")

    @classmethod
    def parse(cls, spec: str) -> Self:
        return cls(*parse_shard(spec))

    def __str__(self) -> str:
        return f"{self.part}/{self.total}"

    def owns(self, index: int) -> bool:
        return index % self.total == self.part - 1

    def select(self, items: Sequence[T]) -> list[T]:
        """The items this part plays, in their original order."""
        return [item for index, item in enumerate(items) if self.owns(index)]
