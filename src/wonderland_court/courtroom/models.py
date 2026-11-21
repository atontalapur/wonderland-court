"""Read-side Courtroom data models derived from shared event contracts and Wave 2 tables."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from wonderland_court.contracts import (
    Event,
    MatchMode,
    MatchSpec,
    ScenarioId,
    Stakes,
    Standing,
    Turn,
)
from wonderland_court.contracts.models import Contract


class RunSummary(Contract):
    """Top-level metadata for a single Wonderland Court run."""

    run_id: str
    mode: MatchMode
    targets: list[str]
    defenses: list[str]
    scenarios: list[ScenarioId]
    rounds: int = Field(ge=1)
    matches: int = Field(ge=0)
    leaks: int = Field(ge=0)
    status: Literal["running", "completed"]
    source: Literal["sqlite", "jsonl", "static"] = "jsonl"


class HeatmapCell(Contract):
    """One Defense × Technique Family (optionally per Scenario) cell."""

    defense: str
    family: str
    scenario: ScenarioId
    matches: int = Field(ge=0)
    leaks: int = Field(ge=0)
    asr: float = Field(ge=0.0, le=1.0)
    match_ids: list[str] = Field(default_factory=list)


class HeatmapData(Contract):
    """Complete Defense × Technique Family heatmap payload."""

    run_id: str
    defenses: list[str]
    families: list[str]
    scenarios: list[ScenarioId]
    cells: list[HeatmapCell]


class MatchTranscript(Contract):
    """Reconstructed full transcript for one match."""

    match: MatchSpec
    stakes: Stakes
    turns: list[Turn] = Field(default_factory=list)
    broken: bool = False
    broken_on_turn: int | None = None
    breaking_family: str | None = None
    status: Literal["running", "broken", "held"] = "running"


class CalibrationSummary(Contract):
    """Queen of Hearts LLM-vs-exact ground-truth agreement metrics."""

    run_id: str
    total_exact_checked: int = Field(ge=0)
    llm_evaluated: int = Field(ge=0)
    agreement_count: int = Field(ge=0)
    agreement_rate: float = Field(ge=0.0, le=1.0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)


class FailureClusterView(Contract):
    """Deduplicated failure family surfaced by Caterpillar."""

    cluster_id: str
    family_label: str
    technique_family: str
    scenario: ScenarioId
    count: int = Field(ge=0)
    example_match_ids: list[str] = Field(default_factory=list)
    root_cause_summary: str


class RemediationAdviceView(Contract):
    """Caterpillar failure grouping + recommended hardened config."""

    run_id: str
    target_kind: str
    clusters: list[FailureClusterView] = Field(default_factory=list)
    recommended_defense: str
    config_patch_yaml: str
    rationale: str


class RetrialComparisonView(Contract):
    """Before vs. after comparison on identical seeds after Caterpillar fix."""

    baseline_run_id: str
    retrial_run_id: str
    matched_seeds: list[int] = Field(default_factory=list)
    baseline_asr: float = Field(ge=0.0, le=1.0)
    retrial_asr: float = Field(ge=0.0, le=1.0)
    asr_delta: float
    baseline_utility: float | None = None
    retrial_utility: float | None = None
    per_scenario_diff: dict[str, dict[str, float]] = Field(default_factory=dict)


class RunBundle(Contract):
    """Complete read-only Courtroom snapshot for UI, reports, and static export."""

    summary: RunSummary
    events: list[Event]
    matches: list[MatchTranscript]
    standings: list[Standing]
    heatmap: HeatmapData
    calibration: CalibrationSummary | None = None
    advice: RemediationAdviceView | None = None
    retrial: RetrialComparisonView | None = None
