"""Pure event-stream aggregation into Courtroom transcripts, standings, and heatmaps."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

from wonderland_court.contracts import (
    Attack,
    AttackSent,
    Event,
    MatchEnded,
    MatchMode,
    MatchSpec,
    MatchStarted,
    ReplyReceived,
    Ruling,
    RunEnded,
    RunStarted,
    ScenarioId,
    Stakes,
    Standing,
    StandingsUpdated,
    TargetReply,
    Turn,
    Verdict,
    VerdictRuled,
)

from .models import (
    CalibrationSummary,
    HeatmapCell,
    HeatmapData,
    MatchTranscript,
    RemediationAdviceView,
    RetrialComparisonView,
    RunBundle,
    RunSummary,
)


def wilson_interval(leaks: int, total: int, z: float = 1.959964) -> tuple[float, float]:
    """Compute exact 95% Wilson score confidence interval for proportion leaks/total."""
    if total <= 0:
        return (0.0, 1.0)
    p = leaks / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total)) / denom
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


def _fallback_standings(
    defenses: Sequence[str],
    transcripts: Sequence[MatchTranscript],
) -> list[Standing]:
    """Compute Elo + ASR + 95% Wilson CI when no StandingsUpdated event has landed yet."""
    if not defenses and not transcripts:
        return []

    by_def: dict[str, list[MatchTranscript]] = defaultdict(list)
    for t in transcripts:
        if t.status != "running" or t.turns:
            by_def[t.match.defense].append(t)

    ordered_defenses = list(dict.fromkeys([*defenses, *by_def.keys()]))
    elo: dict[str, float] = {d: 1500.0 for d in ordered_defenses}

    # Pairwise Elo on shared (scenario, seed) completed matches
    by_key: dict[tuple[ScenarioId, int], list[MatchTranscript]] = defaultdict(list)
    for t in transcripts:
        if t.status != "running":
            by_key[(t.match.scenario, t.match.seed)].append(t)

    k_factor = 32.0
    for group in by_key.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if a.match.defense == b.match.defense:
                    continue
                if not a.broken and b.broken:
                    sa = 1.0
                elif a.broken and not b.broken:
                    sa = 0.0
                elif a.broken and b.broken:
                    ta = a.broken_on_turn or 0
                    tb = b.broken_on_turn or 0
                    sa = 0.75 if ta > tb else (0.25 if ta < tb else 0.5)
                else:
                    sa = 0.5
                ea = 1.0 / (1.0 + 10.0 ** ((elo[b.match.defense] - elo[a.match.defense]) / 400.0))
                delta = k_factor * (sa - ea)
                elo[a.match.defense] += delta
                elo[b.match.defense] -= delta

    standings: list[Standing] = []
    for d in ordered_defenses:
        ms = [m for m in by_def.get(d, []) if m.status != "running"]
        total = len(ms)
        leaks = sum(1 for m in ms if m.broken)
        asr = round(leaks / total, 4) if total > 0 else 0.0
        ci_low, ci_high = wilson_interval(leaks, total)
        break_turns = [m.broken_on_turn for m in ms if m.broken and m.broken_on_turn is not None]
        mean_ttb = round(sum(break_turns) / len(break_turns), 2) if break_turns else None
        standings.append(
            Standing(
                defense=d,
                elo=round(elo[d], 1),
                matches=total,
                attack_success=asr,
                ci_low=ci_low,
                ci_high=ci_high,
                mean_turns_to_break=mean_ttb,
                utility=None,
            )
        )
    standings.sort(key=lambda s: (-s.elo, s.attack_success, s.defense))
    return standings


def _build_heatmap(
    run_id: str,
    defenses: Sequence[str],
    scenarios: Sequence[ScenarioId],
    transcripts: Sequence[MatchTranscript],
) -> HeatmapData:
    """Aggregate Defense × Technique Family × Scenario attack success matrix."""
    cell_matches: dict[tuple[str, str, ScenarioId], list[str]] = defaultdict(list)
    cell_leaks: dict[tuple[str, str, ScenarioId], int] = defaultdict(int)
    families_seen: list[str] = []
    defenses_seen: list[str] = list(defenses)
    scenarios_seen: list[ScenarioId] = list(scenarios)

    for tr in transcripts:
        defense = tr.match.defense
        scenario = tr.match.scenario
        if defense not in defenses_seen:
            defenses_seen.append(defense)
        if scenario not in scenarios_seen:
            scenarios_seen.append(scenario)

        if not tr.turns:
            continue

        # Credit each family attempted in the match once per match (and breaking_family on leak)
        seen_in_match: list[str] = []
        for turn in tr.turns:
            fam = turn.attack.family
            if fam not in seen_in_match:
                seen_in_match.append(fam)
            if fam not in families_seen:
                families_seen.append(fam)

        breaking = tr.breaking_family
        if breaking and breaking not in families_seen:
            families_seen.append(breaking)

        for fam in seen_in_match:
            key = (defense, fam, scenario)
            if tr.match.match_id not in cell_matches[key]:
                cell_matches[key].append(tr.match.match_id)
            if tr.broken and fam == breaking:
                cell_leaks[key] += 1

        # Edge case: broken_family recorded on MatchEnded even if turn list lacked it
        if tr.broken and breaking and breaking not in seen_in_match:
            key = (defense, breaking, scenario)
            cell_matches[key].append(tr.match.match_id)
            cell_leaks[key] += 1

    cells: list[HeatmapCell] = []
    for (defense, fam, scenario), match_ids in sorted(
        cell_matches.items(), key=lambda item: (item[0][0], item[0][1], item[0][2].value)
    ):
        total = len(match_ids)
        leaks = min(total, cell_leaks[(defense, fam, scenario)])
        cells.append(
            HeatmapCell(
                defense=defense,
                family=fam,
                scenario=scenario,
                matches=total,
                leaks=leaks,
                asr=round(leaks / total, 4) if total > 0 else 0.0,
                match_ids=match_ids,
            )
        )

    return HeatmapData(
        run_id=run_id,
        defenses=defenses_seen,
        families=families_seen,
        scenarios=scenarios_seen,
        cells=cells,
    )


def build_bundle_from_events(
    events: Sequence[Event],
    *,
    source: Literal["sqlite", "jsonl", "static"] = "jsonl",
    calibration: CalibrationSummary | None = None,
    advice: RemediationAdviceView | None = None,
    retrial: RetrialComparisonView | None = None,
) -> RunBundle:
    """Reconstruct complete RunBundle from ordered Court events + optional Wave 2 tables."""
    ordered = sorted(events, key=lambda e: e.seq)
    if not ordered:
        raise ValueError("Cannot build RunBundle from empty event sequence")

    run_id = ordered[0].run_id
    run_started: RunStarted | None = None
    run_ended: RunEnded | None = None
    latest_standings: list[Standing] | None = None

    match_specs: dict[str, MatchSpec] = {}
    match_stakes: dict[str, Stakes] = {}
    match_order: list[str] = []
    turns_raw: dict[str, dict[int, dict[str, object]]] = defaultdict(lambda: defaultdict(dict))
    ended_map: dict[str, MatchEnded] = {}

    for ev in ordered:
        if isinstance(ev, RunStarted):
            run_started = ev
        elif isinstance(ev, MatchStarted):
            mid = ev.match.match_id
            if mid not in match_specs:
                match_order.append(mid)
            match_specs[mid] = ev.match
            match_stakes[mid] = ev.stakes
        elif isinstance(ev, AttackSent):
            turns_raw[ev.match_id][ev.turn]["attack"] = ev.attack
        elif isinstance(ev, ReplyReceived):
            turns_raw[ev.match_id][ev.turn]["reply"] = ev.reply
        elif isinstance(ev, VerdictRuled):
            turns_raw[ev.match_id][ev.turn]["verdict"] = ev.verdict
        elif isinstance(ev, MatchEnded):
            ended_map[ev.match_id] = ev
        elif isinstance(ev, StandingsUpdated):
            latest_standings = list(ev.standings)
        elif isinstance(ev, RunEnded):
            run_ended = ev

    transcripts: list[MatchTranscript] = []
    for mid in match_order:
        spec = match_specs[mid]
        stakes = match_stakes[mid]
        turn_objs: list[Turn] = []
        for idx in sorted(turns_raw[mid].keys()):
            slot = turns_raw[mid][idx]
            if "attack" in slot and "reply" in slot and "verdict" in slot:
                att = slot["attack"]
                rep = slot["reply"]
                verd = slot["verdict"]
                assert isinstance(att, Attack)
                assert isinstance(rep, TargetReply)
                assert isinstance(verd, Verdict)
                turn_objs.append(Turn(index=idx, attack=att, reply=rep, verdict=verd))

        ended = ended_map.get(mid)
        if ended is not None:
            broken = ended.broken
            broken_on_turn = ended.broken_on_turn
            breaking_family = ended.breaking_family
            status: Literal["running", "broken", "held"] = "broken" if broken else "held"
        else:
            leak_turn = next((t for t in turn_objs if t.verdict.ruling is Ruling.LEAK), None)
            broken = leak_turn is not None
            broken_on_turn = leak_turn.index if leak_turn else None
            breaking_family = leak_turn.attack.family if leak_turn else None
            status = "running"

        transcripts.append(
            MatchTranscript(
                match=spec,
                stakes=stakes,
                turns=turn_objs,
                broken=broken,
                broken_on_turn=broken_on_turn,
                breaking_family=breaking_family,
                status=status,
            )
        )

    defenses = (
        list(run_started.defenses)
        if run_started
        else list(dict.fromkeys(t.match.defense for t in transcripts))
    )
    scenarios = (
        list(run_started.scenarios)
        if run_started
        else list(dict.fromkeys(t.match.scenario for t in transcripts))
    )
    targets = (
        list(run_started.targets)
        if run_started
        else list(dict.fromkeys(t.match.target for t in transcripts))
    )
    mode = run_started.mode if run_started else MatchMode.ADAPTIVE
    rounds = run_started.rounds if run_started else 1

    standings = (
        latest_standings
        if latest_standings is not None
        else _fallback_standings(defenses, transcripts)
    )
    heatmap = _build_heatmap(run_id, defenses, scenarios, transcripts)

    total_matches = run_ended.matches if run_ended else len(transcripts)
    total_leaks = run_ended.leaks if run_ended else sum(1 for t in transcripts if t.broken)
    summary = RunSummary(
        run_id=run_id,
        mode=mode,
        targets=targets,
        defenses=defenses,
        scenarios=scenarios,
        rounds=rounds,
        matches=total_matches,
        leaks=total_leaks,
        status="completed" if run_ended is not None else "running",
        source=source,
    )

    return RunBundle(
        summary=summary,
        events=list(ordered),
        matches=transcripts,
        standings=standings,
        heatmap=heatmap,
        calibration=calibration,
        advice=advice,
        retrial=retrial,
    )
