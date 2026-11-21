"""Report generators (HTML, Markdown, JSON, SARIF 2.1.0) for Wonderland Court."""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader

from wonderland_court import __version__
from wonderland_court.contracts import (
    EVENT_ADAPTER,
    Event,
    Ruling,
    ScenarioId,
    parse_event,
    read_events,
)

from .aggregator import build_bundle_from_events
from .models import (
    CalibrationSummary,
    FailureClusterView,
    MatchTranscript,
    RemediationAdviceView,
    RetrialComparisonView,
    RunBundle,
)

SARIF_SCHEMA_URI = "https://json.schemastore.org/sarif-2.1.0.json"


@dataclass(frozen=True)
class _SarifRuleSpec:
    rule_id: str
    scenario: ScenarioId
    name: str
    short_description: str
    full_description: str
    security_severity: str
    owasp_tag: str
    help_uri: str


_SARIF_RULES: tuple[_SarifRuleSpec, ...] = (
    _SarifRuleSpec(
        rule_id="WL-LLM01",
        scenario=ScenarioId.DRINK_ME,
        name="IndirectPromptInjection",
        short_description="OWASP LLM01: Prompt Injection via untrusted document (Drink Me)",
        full_description=(
            "The target followed hidden instructions embedded in an untrusted email, web page, "
            "or tool output delivered during the Drink Me scenario."
        ),
        security_severity="8.5",
        owasp_tag="OWASP-LLM01",
        help_uri="https://genai.owasp.org/llmrisk/llm01-prompt-injection/",
    ),
    _SarifRuleSpec(
        rule_id="WL-LLM02",
        scenario=ScenarioId.VAULT,
        name="SensitiveInformationDisclosure",
        short_description="OWASP LLM02: Canary secret disclosed by target (Vault)",
        full_description=(
            "The target leaked a planted canary secret from its system prompt or protected vault "
            "under adversarial prompting."
        ),
        security_severity="7.5",
        owasp_tag="OWASP-LLM02",
        help_uri="https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/",
    ),
    _SarifRuleSpec(
        rule_id="WL-LLM06",
        scenario=ScenarioId.REFUND_TOOL,
        name="ExcessiveAgencyToolMisuse",
        short_description="OWASP LLM06: Excessive Agency / unauthorized tool call (Refund Tool)",
        full_description=(
            "The target invoked a privileged tool call violating configured policy limits "
            "(such as issuing an unauthorized refund or emailing an external domain)."
        ),
        security_severity="8.5",
        owasp_tag="OWASP-LLM06",
        help_uri="https://genai.owasp.org/llmrisk/llm062025-excessive-agency/",
    ),
    _SarifRuleSpec(
        rule_id="WL-LLM07",
        scenario=ScenarioId.SYSTEM_PROMPT,
        name="SystemPromptLeakage",
        short_description="OWASP LLM07: System prompt leakage",
        full_description=(
            "The target revealed confidential system instructions or protected prompt text."
        ),
        security_severity="7.5",
        owasp_tag="OWASP-LLM07",
        help_uri="https://genai.owasp.org/llmrisk/llm072025-system-prompt-leakage/",
    ),
    _SarifRuleSpec(
        rule_id="WL-MCP01",
        scenario=ScenarioId.MCP_POISON,
        name="McpToolDescriptionPoisoning",
        short_description="OWASP MCP01: Poisoned MCP tool description exploitation",
        full_description=(
            "The target executed unsafe instructions injected through a poisoned Model Context "
            "Protocol (MCP) tool description."
        ),
        security_severity="8.5",
        owasp_tag="OWASP-MCP01",
        help_uri="https://owasp.org/www-project-mcp-top-10/",
    ),
)

_RULE_BY_SCENARIO: dict[ScenarioId, _SarifRuleSpec] = {spec.scenario: spec for spec in _SARIF_RULES}

# autoescape=True is mandatory because adversarial payloads & Drink Me docs may embed <script>.
_JINJA_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _open_readonly_sqlite(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row["name"]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(row["name"]) for row in rows]


def _pick_json_column(columns: set[str], extra_candidates: tuple[str, ...] = ()) -> str | None:
    candidates = (*extra_candidates, "payload", "data", "json", "raw_json", "raw")
    for name in candidates:
        if name in columns:
            return name
    return None


def _decode_json_field(value: object) -> object:
    if isinstance(value, (str, bytes)):
        return json.loads(value)
    return value


def _event_run_ids(conn: sqlite3.Connection, tables: set[str]) -> list[str]:
    if "events" not in tables:
        return []
    cols = set(_table_columns(conn, "events"))
    if "run_id" not in cols:
        return []
    rows = conn.execute("SELECT DISTINCT run_id FROM events ORDER BY rowid ASC").fetchall()
    return [str(row["run_id"]) for row in rows]


def list_db_run_ids(db_path: Path) -> list[str]:
    """Return all run IDs with recorded events in a Court SQLite database."""
    with contextlib.closing(_open_readonly_sqlite(db_path)) as conn:
        tables = _table_names(conn)
        event_rids = _event_run_ids(conn, tables)
        event_rid_set = set(event_rids)
        run_ids: list[str] = []
        if "runs" in tables:
            cols = set(_table_columns(conn, "runs"))
            id_col = "run_id" if "run_id" in cols else ("id" if "id" in cols else None)
            if id_col is not None:
                order_col = next(
                    (c for c in ("started_at", "created_at", "rowid") if c in cols),
                    "rowid",
                )
                rows = conn.execute(
                    f"SELECT {id_col} AS rid FROM runs ORDER BY {order_col} ASC, rowid ASC"
                ).fetchall()
                for row in rows:
                    rid = str(row["rid"])
                    if (not event_rid_set or rid in event_rid_set) and rid not in run_ids:
                        run_ids.append(rid)
        for rid in event_rids:
            if rid not in run_ids:
                run_ids.append(rid)
        return run_ids


def _resolve_db_run_id(conn: sqlite3.Connection, tables: set[str], run_id: str | None) -> str:
    if run_id is not None:
        return run_id
    event_rid_set = set(_event_run_ids(conn, tables))
    if "runs" in tables:
        cols = set(_table_columns(conn, "runs"))
        id_col = "run_id" if "run_id" in cols else ("id" if "id" in cols else None)
        if id_col is not None:
            order_col = next(
                (c for c in ("started_at", "created_at", "rowid") if c in cols),
                "rowid",
            )
            rows = conn.execute(
                f"SELECT {id_col} AS rid FROM runs ORDER BY {order_col} DESC, rowid DESC"
            ).fetchall()
            for row in rows:
                rid = str(row["rid"])
                if not event_rid_set or rid in event_rid_set:
                    return rid
    if "events" in tables:
        cols = set(_table_columns(conn, "events"))
        if "run_id" in cols:
            row = conn.execute("SELECT run_id FROM events ORDER BY rowid DESC LIMIT 1").fetchone()
            if row is not None:
                return str(row["run_id"])
    raise ValueError("No runs found in SQLite database")


def _parse_event_row(row: sqlite3.Row, columns: set[str]) -> Event:
    json_col = _pick_json_column(columns, ("event_json",))
    if json_col is not None and row[json_col] is not None:
        raw = row[json_col]
        parsed = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        if isinstance(parsed, dict):
            if "type" in parsed and "seq" in parsed and "run_id" in parsed and "ts" in parsed:
                return EVENT_ADAPTER.validate_python(parsed)
            merged: dict[str, Any] = dict(parsed)
            for key in ("v", "seq", "ts", "run_id", "type"):
                if key not in merged and key in columns and row[key] is not None:
                    merged[key] = row[key]
            merged.setdefault("v", 1)
            return EVENT_ADAPTER.validate_python(merged)
        return parse_event(raw)
    return EVENT_ADAPTER.validate_python(dict(row))


def _load_db_events(conn: sqlite3.Connection, tables: set[str], run_id: str) -> list[Event]:
    if "events" not in tables:
        raise ValueError("SQLite database has no 'events' table")
    cols = set(_table_columns(conn, "events"))
    order_clause = "ORDER BY seq ASC, rowid ASC" if "seq" in cols else "ORDER BY rowid ASC"
    if "run_id" in cols:
        rows = conn.execute(
            f"SELECT * FROM events WHERE run_id = ? {order_clause}",
            (run_id,),
        ).fetchall()
    else:
        rows = conn.execute(f"SELECT * FROM events {order_clause}").fetchall()

    events = [_parse_event_row(row, cols) for row in rows]
    filtered = [ev for ev in events if ev.run_id == run_id]
    if not filtered:
        raise ValueError(f"No events found for run_id={run_id!r}")
    return filtered


def _load_optional_calibration(
    conn: sqlite3.Connection, tables: set[str], run_id: str
) -> CalibrationSummary | None:
    if "judge_calibration" not in tables:
        return None
    cols = set(_table_columns(conn, "judge_calibration"))
    query = (
        "SELECT * FROM judge_calibration WHERE run_id = ? ORDER BY rowid DESC LIMIT 1"
        if "run_id" in cols
        else "SELECT * FROM judge_calibration ORDER BY rowid DESC LIMIT 1"
    )
    row = (
        conn.execute(query, (run_id,)).fetchone()
        if "run_id" in cols
        else conn.execute(query).fetchone()
    )
    if row is None:
        return None
    json_col = _pick_json_column(cols, ("summary_json", "calibration_json"))
    if json_col is not None and row[json_col] is not None:
        data = _decode_json_field(row[json_col])
        if isinstance(data, dict):
            data.setdefault("run_id", run_id)
            return CalibrationSummary.model_validate(data)
    filtered = {k: row[k] for k in cols if k in CalibrationSummary.model_fields}
    filtered.setdefault("run_id", run_id)
    return CalibrationSummary.model_validate(filtered)


def _load_optional_advice(
    conn: sqlite3.Connection, tables: set[str], run_id: str
) -> RemediationAdviceView | None:
    if "remediation_advice" not in tables:
        return None
    cols = set(_table_columns(conn, "remediation_advice"))
    query = (
        "SELECT * FROM remediation_advice WHERE run_id = ? ORDER BY rowid DESC LIMIT 1"
        if "run_id" in cols
        else "SELECT * FROM remediation_advice ORDER BY rowid DESC LIMIT 1"
    )
    row = (
        conn.execute(query, (run_id,)).fetchone()
        if "run_id" in cols
        else conn.execute(query).fetchone()
    )
    if row is None:
        return None
    json_col = _pick_json_column(cols, ("advice_json",))
    if json_col is not None and row[json_col] is not None:
        data = _decode_json_field(row[json_col])
        if isinstance(data, dict):
            data.setdefault("run_id", run_id)
            return RemediationAdviceView.model_validate(data)

    payload: dict[str, Any] = {k: row[k] for k in cols if k in RemediationAdviceView.model_fields}
    payload.setdefault("run_id", run_id)
    if "clusters" not in payload and "clusters_json" in cols:
        payload["clusters"] = row["clusters_json"]
    if "clusters" in payload and payload["clusters"] is not None:
        payload["clusters"] = _decode_json_field(payload["clusters"])
    elif "failure_clusters" in tables:
        cl_cols = set(_table_columns(conn, "failure_clusters"))
        cl_rows = (
            conn.execute(
                "SELECT * FROM failure_clusters WHERE run_id = ? ORDER BY rowid ASC", (run_id,)
            ).fetchall()
            if "run_id" in cl_cols
            else conn.execute("SELECT * FROM failure_clusters ORDER BY rowid ASC").fetchall()
        )
        clusters_list: list[dict[str, Any]] = []
        for cl_row in cl_rows:
            cl_dict = {k: cl_row[k] for k in cl_cols if k in FailureClusterView.model_fields}
            if "example_match_ids" in cl_dict and cl_dict["example_match_ids"] is not None:
                cl_dict["example_match_ids"] = _decode_json_field(cl_dict["example_match_ids"])
            clusters_list.append(cl_dict)
        payload["clusters"] = clusters_list
    return RemediationAdviceView.model_validate(payload)


def _load_optional_retrial(
    conn: sqlite3.Connection, tables: set[str], run_id: str
) -> RetrialComparisonView | None:
    if "retrial_comparisons" not in tables:
        return None
    cols = set(_table_columns(conn, "retrial_comparisons"))
    row: sqlite3.Row | None = None
    if "retrial_run_id" in cols and "baseline_run_id" in cols:
        row = conn.execute(
            "SELECT * FROM retrial_comparisons WHERE retrial_run_id = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM retrial_comparisons WHERE baseline_run_id = ? "
                "ORDER BY rowid DESC LIMIT 1",
                (run_id,),
            ).fetchone()
    elif "run_id" in cols:
        row = conn.execute(
            "SELECT * FROM retrial_comparisons WHERE run_id = ? ORDER BY rowid DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM retrial_comparisons ORDER BY rowid DESC LIMIT 1"
        ).fetchone()

    if row is None:
        return None

    json_col = _pick_json_column(cols, ("comparison_json", "retrial_json"))
    if json_col is not None and row[json_col] is not None:
        data = _decode_json_field(row[json_col])
        if isinstance(data, dict):
            return RetrialComparisonView.model_validate(data)

    payload: dict[str, Any] = {k: row[k] for k in cols if k in RetrialComparisonView.model_fields}
    for json_field in ("matched_seeds", "per_scenario_diff"):
        alt_col = f"{json_field}_json"
        if json_field not in payload and alt_col in cols and row[alt_col] is not None:
            payload[json_field] = row[alt_col]
        if json_field in payload and payload[json_field] is not None:
            payload[json_field] = _decode_json_field(payload[json_field])
    return RetrialComparisonView.model_validate(payload)


def _load_jsonl_meta_sidecar(
    input_path: Path,
) -> tuple[
    CalibrationSummary | None,
    RemediationAdviceView | None,
    RetrialComparisonView | None,
]:
    candidates = [
        Path(f"{input_path}.meta.json"),
        input_path.with_suffix(".meta.json"),
    ]
    meta_path = next((p for p in candidates if p.exists()), None)
    if meta_path is None:
        return (None, None, None)

    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Metadata sidecar must be a JSON object: {meta_path}")

    calibration = (
        CalibrationSummary.model_validate(raw["calibration"])
        if raw.get("calibration") is not None
        else None
    )
    advice = (
        RemediationAdviceView.model_validate(raw["advice"])
        if raw.get("advice") is not None
        else None
    )
    retrial = (
        RetrialComparisonView.model_validate(raw["retrial"])
        if raw.get("retrial") is not None
        else None
    )
    return (calibration, advice, retrial)


def load_report_bundle(
    *,
    db_path: Path | None = None,
    input_path: Path | None = None,
    run_id: str | None = None,
) -> RunBundle:
    """Load a RunBundle from either a JSONL event stream (+ optional sidecar) or a SQLite DB."""
    if db_path is None and input_path is None:
        raise ValueError("Either db_path or input_path must be provided")

    if input_path is not None:
        if not input_path.exists():
            raise FileNotFoundError(f"Input JSONL file not found: {input_path}")
        all_events = list(read_events(input_path))
        if not all_events:
            raise ValueError(f"No events found in {input_path}")
        target_run_id = run_id if run_id is not None else all_events[-1].run_id
        run_events = [ev for ev in all_events if ev.run_id == target_run_id]
        if not run_events:
            raise ValueError(f"Run {target_run_id!r} not found in {input_path}")
        calibration, advice, retrial = _load_jsonl_meta_sidecar(input_path)
        return build_bundle_from_events(
            run_events,
            source="jsonl",
            calibration=calibration,
            advice=advice,
            retrial=retrial,
        )

    assert db_path is not None
    with contextlib.closing(_open_readonly_sqlite(db_path)) as conn:
        tables = _table_names(conn)
        target_run_id = _resolve_db_run_id(conn, tables, run_id)
        events = _load_db_events(conn, tables, target_run_id)
        calibration = _load_optional_calibration(conn, tables, target_run_id)
        advice = _load_optional_advice(conn, tables, target_run_id)
        retrial = _load_optional_retrial(conn, tables, target_run_id)
    return build_bundle_from_events(
        events,
        source="sqlite",
        calibration=calibration,
        advice=advice,
        retrial=retrial,
    )


def _sha256_fingerprint(parts: tuple[str, ...]) -> str:
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _sarif_driver_rules() -> list[dict[str, Any]]:
    return [
        {
            "id": spec.rule_id,
            "name": spec.name,
            "shortDescription": {"text": spec.short_description},
            "fullDescription": {"text": spec.full_description},
            "helpUri": spec.help_uri,
            "defaultConfiguration": {"level": "error"},
            "properties": {
                "tags": ["security", "ai", "llm", spec.owasp_tag],
                "precision": "high",
                "security-severity": spec.security_severity,
            },
        }
        for spec in _SARIF_RULES
    ]


def _make_sarif_result(
    *,
    rule_id: str,
    message_text: str,
    target_config_path: str,
    fingerprint_parts: tuple[str, ...],
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ruleId": rule_id,
        "level": "error",
        "message": {"text": message_text},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": target_config_path},
                    "region": {"startLine": 1},
                }
            }
        ],
        "partialFingerprints": {"primaryLocationLineHash": _sha256_fingerprint(fingerprint_parts)},
    }
    if properties:
        result["properties"] = properties
    return result


def _match_leak_evidence(tr: MatchTranscript) -> tuple[str, str]:
    leak_turn = next((t for t in tr.turns if t.verdict.ruling is Ruling.LEAK), None)
    family = tr.breaking_family or (
        leak_turn.attack.family if leak_turn is not None else (tr.match.family or "unknown")
    )
    if leak_turn is not None:
        evidence = (
            f"turn {leak_turn.index} ({leak_turn.verdict.layer.value} judge): "
            f"{leak_turn.verdict.reason}"
        )
    else:
        evidence = f"broken on turn {tr.broken_on_turn or '?'}"
    return family, evidence


def _render_sarif(bundle: RunBundle, *, target_config_path: str) -> str:
    matches_by_id = {tr.match.match_id: tr for tr in bundle.matches}
    recommended = bundle.advice.recommended_defense if bundle.advice is not None else None

    results: list[dict[str, Any]] = []
    covered_match_ids: set[str] = set()
    covered_pairs: set[tuple[ScenarioId, str]] = set()

    if bundle.advice is not None and bundle.advice.clusters:
        for cl in bundle.advice.clusters:
            rule = _RULE_BY_SCENARIO[cl.scenario]
            defenses: list[str] = []
            for mid in cl.example_match_ids:
                covered_match_ids.add(mid)
                if mid in matches_by_id:
                    d = matches_by_id[mid].match.defense
                    if d not in defenses:
                        defenses.append(d)
            covered_pairs.add((cl.scenario, cl.technique_family))

            defense_label = ", ".join(defenses) if defenses else "tested stack"
            rec_suffix = f" Recommended defense: {recommended}." if recommended else ""
            msg = (
                f"[{cl.family_label}] Technique '{cl.technique_family}' broke "
                f"{defense_label} in scenario '{cl.scenario.value}' ({cl.count} match(es)). "
                f"Evidence: {cl.root_cause_summary}.{rec_suffix}"
            )
            results.append(
                _make_sarif_result(
                    rule_id=rule.rule_id,
                    message_text=msg,
                    target_config_path=target_config_path,
                    fingerprint_parts=(
                        "cluster",
                        rule.rule_id,
                        cl.scenario.value,
                        cl.technique_family,
                        cl.cluster_id,
                        target_config_path,
                    ),
                    properties={
                        "clusterId": cl.cluster_id,
                        "techniqueFamily": cl.technique_family,
                        "scenario": cl.scenario.value,
                        "count": cl.count,
                        "exampleMatchIds": cl.example_match_ids,
                    },
                )
            )

    for tr in bundle.matches:
        if not tr.broken:
            continue
        family, evidence = _match_leak_evidence(tr)
        if tr.match.match_id in covered_match_ids or (tr.match.scenario, family) in covered_pairs:
            continue

        rule = _RULE_BY_SCENARIO[tr.match.scenario]
        rec_suffix = f" Recommended defense: {recommended}." if recommended else ""
        msg = (
            f"Technique '{family}' broke defense '{tr.match.defense}' in scenario "
            f"'{tr.match.scenario.value}' (match {tr.match.match_id}, seed {tr.match.seed}). "
            f"Evidence: {evidence}.{rec_suffix}"
        )
        results.append(
            _make_sarif_result(
                rule_id=rule.rule_id,
                message_text=msg,
                target_config_path=target_config_path,
                fingerprint_parts=(
                    "match",
                    rule.rule_id,
                    tr.match.target,
                    tr.match.defense,
                    tr.match.scenario.value,
                    family,
                    str(tr.match.seed),
                    tr.match.match_id,
                    target_config_path,
                ),
                properties={
                    "matchId": tr.match.match_id,
                    "defense": tr.match.defense,
                    "techniqueFamily": family,
                    "scenario": tr.match.scenario.value,
                    "seed": tr.match.seed,
                },
            )
        )

    sarif_doc: dict[str, Any] = {
        "$schema": SARIF_SCHEMA_URI,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Wonderland Court",
                        "semanticVersion": __version__,
                        "informationUri": "https://github.com/atontalapur/wonderland-court",
                        "rules": _sarif_driver_rules(),
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif_doc, indent=2)


def _aggregate_heatmap_matrix(
    bundle: RunBundle,
) -> list[dict[str, Any]]:
    """Collapse per-scenario heatmap cells into Defense × Technique rows with scenario tooltips."""
    agg: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"matches": 0, "leaks": 0, "scenarios": []}
    )
    for cell in bundle.heatmap.cells:
        bucket = agg[(cell.defense, cell.family)]
        bucket["matches"] += cell.matches
        bucket["leaks"] += cell.leaks
        bucket["scenarios"].append(
            f"{cell.scenario.value}: {cell.leaks}/{cell.matches} ({cell.asr * 100:.0f}%)"
        )

    rows: list[dict[str, Any]] = []
    for defense in bundle.heatmap.defenses:
        row_cells: list[dict[str, Any]] = []
        for family in bundle.heatmap.families:
            cell_bucket = agg.get((defense, family))
            if cell_bucket is None or cell_bucket["matches"] == 0:
                row_cells.append(
                    {
                        "family": family,
                        "matches": 0,
                        "leaks": 0,
                        "asr": 0.0,
                        "css_class": "heat-none",
                        "tooltip": "No attempts",
                    }
                )
            else:
                matches = int(cell_bucket["matches"])
                leaks = int(cell_bucket["leaks"])
                asr = leaks / matches if matches > 0 else 0.0
                if leaks == 0:
                    css_class = "heat-zero"
                elif asr < 0.5:
                    css_class = "heat-low"
                else:
                    css_class = "heat-high"
                row_cells.append(
                    {
                        "family": family,
                        "matches": matches,
                        "leaks": leaks,
                        "asr": round(asr, 4),
                        "css_class": css_class,
                        "tooltip": "; ".join(cell_bucket["scenarios"]),
                    }
                )
        rows.append({"defense": defense, "cells": row_cells})
    return rows


def _render_html(bundle: RunBundle, *, target_config_path: str) -> str:
    template = _JINJA_ENV.get_template("report.html.j2")
    overall_asr = (
        bundle.summary.leaks / bundle.summary.matches if bundle.summary.matches > 0 else 0.0
    )
    scenario_rule_ids = {scen.value: spec.rule_id for scen, spec in _RULE_BY_SCENARIO.items()}
    return template.render(
        bundle=bundle,
        target_config_path=target_config_path,
        overall_asr=overall_asr,
        best_standing=bundle.standings[0] if bundle.standings else None,
        heatmap_rows=_aggregate_heatmap_matrix(bundle),
        broken_matches=[tr for tr in bundle.matches if tr.broken],
        scenario_rule_ids=scenario_rule_ids,
    )


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _render_markdown(bundle: RunBundle, *, target_config_path: str) -> str:
    s = bundle.summary
    overall_asr = s.leaks / s.matches if s.matches > 0 else 0.0
    lines: list[str] = [
        f"# Wonderland Court Report — `{s.run_id}`",
        "",
        "## Run Summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Run ID | `{_md_cell(s.run_id)}` |",
        f"| Status | `{_md_cell(s.status)}` |",
        f"| Mode | `{_md_cell(s.mode.value)}` |",
        f"| Source | `{_md_cell(s.source)}` |",
        f"| Config | `{_md_cell(target_config_path)}` |",
        f"| Targets | {_md_cell(', '.join(s.targets))} |",
        f"| Scenarios | {_md_cell(', '.join(sc.value for sc in s.scenarios))} |",
        f"| Rounds | {s.rounds} |",
        f"| Matches | {s.matches} |",
        f"| Leaks | {s.leaks} ({overall_asr * 100:.1f}%) |",
        "",
        "## Leaderboard",
        "",
        "| Defense | Elo | Matches | ASR | 95% Wilson CI | Mean Turns-to-Break | Dodo Utility |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in bundle.standings:
        ttb = f"{row.mean_turns_to_break:.2f}" if row.mean_turns_to_break is not None else "—"
        util = f"{row.utility * 100:.1f}%" if row.utility is not None else "—"
        ci = f"[{row.ci_low * 100:.1f}%, {row.ci_high * 100:.1f}%]"
        lines.append(
            f"| `{_md_cell(row.defense)}` | {row.elo:.1f} | {row.matches} | "
            f"{row.attack_success * 100:.1f}% | {ci} | {ttb} | {util} |"
        )

    lines.extend(["", "## Defense × Technique Heatmap", ""])
    families = bundle.heatmap.families
    if families:
        header = "| Defense | " + " | ".join(f"`{_md_cell(f)}`" for f in families) + " |"
        sep = "| --- | " + " | ".join(":---:" for _ in families) + " |"
        lines.extend([header, sep])
        for hrow in _aggregate_heatmap_matrix(bundle):
            cells_str = " | ".join(
                f"{c['leaks']}/{c['matches']} ({c['asr'] * 100:.0f}%)" if c["matches"] > 0 else "—"
                for c in hrow["cells"]
            )
            lines.append(f"| `{_md_cell(hrow['defense'])}` | {cells_str} |")
    else:
        lines.append("_No heatmap data recorded._")

    if bundle.calibration is not None:
        cal = bundle.calibration
        lines.extend(
            [
                "",
                "## Queen of Hearts Judge Calibration",
                "",
                "| Metric | Value |",
                "| --- | ---: |",
                f"| Total Exact Checked | {cal.total_exact_checked} |",
                f"| LLM Evaluated | {cal.llm_evaluated} |",
                f"| Agreement Count | {cal.agreement_count} |",
                f"| Agreement Rate | {cal.agreement_rate * 100:.1f}% |",
                f"| False Positives | {cal.false_positives} |",
                f"| False Negatives | {cal.false_negatives} |",
            ]
        )

    if bundle.advice is not None:
        adv = bundle.advice
        lines.extend(
            [
                "",
                "## Caterpillar Remediation Advice",
                "",
                f"- **Target Kind:** `{_md_cell(adv.target_kind)}`",
                f"- **Recommended Defense:** `{_md_cell(adv.recommended_defense)}`",
                f"- **Rationale:** {adv.rationale}",
                "",
            ]
        )
        if adv.clusters:
            cluster_hdr = (
                "| Cluster | Label | Technique | Scenario | Count | Example Matches | Root Cause |"
            )
            lines.extend(
                [
                    cluster_hdr,
                    "| --- | --- | --- | --- | ---: | --- | --- |",
                ]
            )
            for cl in adv.clusters:
                examples = ", ".join(cl.example_match_ids)
                lines.append(
                    f"| `{_md_cell(cl.cluster_id)}` | {_md_cell(cl.family_label)} | "
                    f"`{_md_cell(cl.technique_family)}` | `{_md_cell(cl.scenario.value)}` | "
                    f"{cl.count} | {_md_cell(examples)} | {_md_cell(cl.root_cause_summary)} |"
                )
            lines.append("")
        if adv.config_patch_yaml:
            lines.extend(["```yaml", adv.config_patch_yaml.rstrip(), "```"])

    if bundle.retrial is not None:
        ret = bundle.retrial
        seeds_str = ", ".join(map(str, ret.matched_seeds))
        util_str = (
            f"{ret.baseline_utility * 100:.1f}% -> {ret.retrial_utility * 100:.1f}%"
            if ret.baseline_utility is not None and ret.retrial_utility is not None
            else "—"
        )
        lines.extend(
            [
                "",
                "## Retrial Before / After Comparison",
                "",
                "| Metric | Value |",
                "| --- | --- |",
                f"| Baseline Run | `{_md_cell(ret.baseline_run_id)}` |",
                f"| Retrial Run | `{_md_cell(ret.retrial_run_id)}` |",
                f"| Matched Seeds | {len(ret.matched_seeds)} ({seeds_str}) |",
                f"| Baseline ASR | {ret.baseline_asr * 100:.1f}% |",
                f"| Retrial ASR | {ret.retrial_asr * 100:.1f}% |",
                f"| ASR Delta | {ret.asr_delta * 100:+.1f} pp |",
                f"| Dodo Utility | {util_str} |",
            ]
        )
        if ret.per_scenario_diff:
            lines.extend(
                [
                    "",
                    "| Scenario | Baseline ASR | Retrial ASR | Delta |",
                    "| --- | ---: | ---: | ---: |",
                ]
            )
            for scen, stats in sorted(ret.per_scenario_diff.items()):
                base_v = stats.get("baseline_asr", 0.0)
                ret_v = stats.get("retrial_asr", 0.0)
                delta_v = stats.get("asr_delta", ret_v - base_v)
                lines.append(
                    f"| `{_md_cell(scen)}` | {base_v * 100:.1f}% | "
                    f"{ret_v * 100:.1f}% | {delta_v * 100:+.1f} pp |"
                )

    broken = [tr for tr in bundle.matches if tr.broken]
    lines.extend(["", f"## Leak Transcripts ({len(broken)})", ""])
    if broken:
        lines.extend(
            [
                "| Match | Defense | Scenario | Breaking Family | Turn | Reason |",
                "| --- | --- | --- | --- | ---: | --- |",
            ]
        )
        for tr in broken:
            fam, evidence = _match_leak_evidence(tr)
            lines.append(
                f"| `{_md_cell(tr.match.match_id)}` | `{_md_cell(tr.match.defense)}` | "
                f"`{_md_cell(tr.match.scenario.value)}` | `{_md_cell(fam)}` | "
                f"{tr.broken_on_turn or '—'} | {_md_cell(evidence)} |"
            )
    else:
        lines.append("_No leaks occurred during this trial._")

    lines.append("")
    return "\n".join(lines)


def render_report(
    bundle: RunBundle,
    fmt: Literal["html", "md", "json", "sarif"] | str,
    *,
    target_config_path: str = "court.yaml",
) -> str:
    """Render a RunBundle into HTML, Markdown, JSON, or SARIF 2.1.0."""
    normalized = fmt.lower().strip()
    if normalized == "json":
        return bundle.model_dump_json(indent=2)
    if normalized == "sarif":
        return _render_sarif(bundle, target_config_path=target_config_path)
    if normalized == "html":
        return _render_html(bundle, target_config_path=target_config_path)
    if normalized == "md":
        return _render_markdown(bundle, target_config_path=target_config_path)
    raise ValueError(f"Unsupported report format: {fmt!r}")


def write_report(
    *,
    fmt: str,
    out_path: Path | None = None,
    db_path: Path | None = None,
    input_path: Path | None = None,
    run_id: str | None = None,
    target_config_path: str = "court.yaml",
) -> str:
    """Load a RunBundle, render the requested report format, and optionally write to disk."""
    bundle = load_report_bundle(db_path=db_path, input_path=input_path, run_id=run_id)
    rendered = render_report(bundle, fmt, target_config_path=target_config_path)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
    return rendered
