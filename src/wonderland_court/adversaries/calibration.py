"""Queen of Hearts calibration: how often the LLM judge (layer 4) agrees with the exact layers.

The ground truth is every recorded turn whose verdict came from an exact layer, canary
(`JudgeLayer.CANARY`) or tool call (`JudgeLayer.TOOL_CALL`). A sample of those turns is ruled
again by `QueenJudge.judge_with_llm_only`, which skips layers 1 to 3, and the two rulings are
compared. A false positive is the LLM ruling LEAK where the exact check said HELD; a false
negative is the reverse.

The sample is stratified half LEAK and half HELD as far as the data allows, capped at
`sample_size`, and fixed by `seed`. An LLM reply the judge cannot parse (the judge falls back
to HELD at the similarity layer) is not an LLM ruling, so it is left out of `llm_evaluated`
and the agreement counts.

`calibrate` works over `run_view.MatchRecord`s. `calibrate_run` loads one run from the
Engine's `CourtStore`, calibrates it and saves the row to the `judge_calibration` table, where
the Courtroom dashboard and reports read it. A run with no parseable LLM ruling gets no row:
it shows as not calibrated rather than as 0% agreement.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from wonderland_court.contracts.models import JudgeLayer, Ruling, Stakes, Turn, Verdict
from wonderland_court.engine.store import CourtStore, JudgeCalibration

from .judge import QueenJudge
from .run_view import MatchRecord, matches_from_events

EXACT_LAYERS: frozenset[JudgeLayer] = frozenset({JudgeLayer.CANARY, JudgeLayer.TOOL_CALL})
"""Layers whose verdicts are ground truth."""


@dataclass(frozen=True)
class ExactSample:
    """One turn ruled by an exact layer, with the stakes it was judged against."""

    match_id: str
    stakes: Stakes
    turn: Turn


@dataclass(frozen=True)
class CalibrationResult:
    """One row of the `judge_calibration` table (#4).

    `agreement_rate` is `agreement_count / llm_evaluated`, or `None` when nothing was
    evaluated.
    """

    run_id: str
    total_exact_checked: int
    llm_evaluated: int
    agreement_count: int
    agreement_rate: float | None
    false_positives: int
    false_negatives: int

    def to_row(self) -> dict[str, Any]:
        return asdict(self)

    def to_judge_calibration(self) -> JudgeCalibration | None:
        """The store's row, or None when `agreement_rate` is None.

        The store and the Courtroom read `agreement_rate` as a number from 0 to 1. With no
        LLM ruling there is no rate, and 0.0 would read as a judge that always disagrees.
        """
        if self.agreement_rate is None:
            return None
        return JudgeCalibration(
            run_id=self.run_id,
            total_exact_checked=self.total_exact_checked,
            llm_evaluated=self.llm_evaluated,
            agreement_count=self.agreement_count,
            agreement_rate=self.agreement_rate,
            false_positives=self.false_positives,
            false_negatives=self.false_negatives,
        )


def exact_turns(records: Sequence[MatchRecord]) -> list[ExactSample]:
    """Every turn whose verdict came from an exact layer, in record and turn order."""
    return [
        ExactSample(record.match.match_id, record.stakes, turn)
        for record in records
        for turn in record.turns
        if turn.verdict.layer in EXACT_LAYERS
    ]


def sample_exact_turns(
    records: Sequence[MatchRecord], *, sample_size: int = 30, seed: int = 42
) -> list[ExactSample]:
    """Up to `sample_size` exact-layer turns, half LEAK and half HELD when both are there.

    LEAK gets `sample_size // 2` slots and HELD the rest; a side that runs short hands its
    unused slots to the other. The picks are fixed by `seed` and returned in record and turn
    order. Raises ValueError for a `sample_size` below 1.
    """
    if sample_size < 1:
        raise ValueError(f"sample_size must be at least 1, got {sample_size}")
    pool = exact_turns(records)
    leaks = [i for i, s in enumerate(pool) if s.turn.verdict.ruling is Ruling.LEAK]
    helds = [i for i, s in enumerate(pool) if s.turn.verdict.ruling is Ruling.HELD]
    n = min(sample_size, len(pool))
    n_leak = min(len(leaks), n // 2)
    n_held = min(len(helds), n - n_leak)
    n_leak = min(len(leaks), n - n_held)
    rng = random.Random(seed)
    picked = rng.sample(leaks, n_leak) + rng.sample(helds, n_held)
    return [pool[i] for i in sorted(picked)]


def _run_id(records: Sequence[MatchRecord]) -> str:
    run_ids = {record.run_id for record in records}
    if len(run_ids) != 1:
        found = ", ".join(sorted(run_ids)) or "none"
        raise ValueError(f"calibrate needs the records of exactly one run, got run ids: {found}")
    return run_ids.pop()


async def calibrate(
    records: Sequence[MatchRecord],
    queen: QueenJudge,
    *,
    sample_size: int = 30,
    seed: int = 42,
) -> CalibrationResult:
    """Measure the LLM judge against the exact layers over one run's matches.

    `queen` needs an `llm` client; `judge_with_llm_only` raises RuntimeError without one.
    Raises ValueError when `records` is empty or spans more than one run, or for a
    `sample_size` below 1.
    """
    run_id = _run_id(records)
    total = len(exact_turns(records))
    samples = sample_exact_turns(records, sample_size=sample_size, seed=seed)
    verdicts: list[Verdict] = await asyncio.gather(
        *(queen.judge_with_llm_only(s.stakes, s.turn.attack, s.turn.reply) for s in samples)
    )
    evaluated = agreed = false_positives = false_negatives = 0
    for sample, llm in zip(samples, verdicts, strict=True):
        if llm.layer is not JudgeLayer.LLM:
            continue  # unparseable LLM output, not a ruling
        evaluated += 1
        exact = sample.turn.verdict.ruling
        if llm.ruling is exact:
            agreed += 1
        elif llm.ruling is Ruling.LEAK:
            false_positives += 1
        else:
            false_negatives += 1
    return CalibrationResult(
        run_id=run_id,
        total_exact_checked=total,
        llm_evaluated=evaluated,
        agreement_count=agreed,
        agreement_rate=agreed / evaluated if evaluated else None,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


async def calibrate_run(
    run_id: str,
    store: CourtStore,
    queen: QueenJudge,
    *,
    sample_size: int = 30,
    seed: int = 42,
) -> CalibrationResult:
    """Calibrate one recorded run and save the result to the store's `judge_calibration`.

    The run's events are rebuilt with `matches_from_events` and passed to `calibrate`. The
    row replaces any earlier one for the run, and is skipped when `agreement_rate` is None
    (see `CalibrationResult.to_judge_calibration`). Give `queen` the shared rate-limited
    client as its `llm`. Raises ValueError when the run has no recorded matches.
    """
    records = matches_from_events(await store.get_events_after(run_id))
    if not records:
        raise ValueError(f"no matches recorded for run {run_id!r}")
    result = await calibrate(records, queen, sample_size=sample_size, seed=seed)
    row = result.to_judge_calibration()
    if row is not None:
        await store.save_judge_calibration(row)
    return result
