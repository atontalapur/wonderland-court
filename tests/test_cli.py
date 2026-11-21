import json
import re
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from typer.main import get_command
from typer.testing import CliRunner, Result

from wonderland_court import __version__, registry
from wonderland_court.cli import app
from wonderland_court.contracts import (
    MatchStarted,
    MutatorId,
    TechniqueFamily,
    parse_event,
)

runner = CliRunner()
WIDE = {"COLUMNS": "200", "NO_COLOR": "1"}

COMMANDS = ["init", "doctor", "trial", "serve", "report", "ci", "advise", "retrial"]
STUBS = ["init", "doctor", "ci", "retrial"]


def invoke(*args: str) -> Result:
    return runner.invoke(app, list(args), env=WIDE)


def test_version() -> None:
    result = invoke("--version")
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_every_command() -> None:
    result = invoke("--help")
    assert result.exit_code == 0
    for command in COMMANDS:
        assert command in result.output


@pytest.mark.parametrize("command", STUBS)
def test_stubs_fail_until_built(command: str) -> None:
    result = invoke(command)
    assert result.exit_code == 1
    assert "isn't built yet" in result.output


@pytest.mark.parametrize(
    ("command", "loader", "component"),
    [
        ("serve", "load_server_runner", registry.SERVER_RUNNER),
        ("report", "load_report_renderer", registry.REPORT_RENDERER),
        ("advise", "load_remediator", registry.REMEDIATOR),
    ],
)
def test_track_commands_say_when_their_track_is_not_built(
    command: str,
    loader: str,
    component: registry.Component,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(registry, loader, lambda config, client: registry.NotBuilt(component))
    result = invoke(command)
    assert result.exit_code == 1
    assert f"{component.module} isn't built yet ({component.issue})" in result.output


def test_trial_exposes_selectable_tactics() -> None:
    """Rich help truncates on narrow CI terminals, so assert on the Click params."""
    root = cast(Any, get_command(app))
    trial = root.commands["trial"]
    opts = {opt: param for param in trial.params for opt in param.opts}
    for option in ("--family", "--mutator", "--mock", "--db", "--quick", "--mode"):
        assert option in opts
    assert "Technique family" in (opts["--family"].help or "")
    assert "Mad Hatter mutator" in (opts["--mutator"].help or "")
    assert TechniqueFamily.FOOT_IN_THE_DOOR.value == "foot_in_the_door"
    assert MutatorId.LOW_RESOURCE_LANGUAGE.value == "low_resource_language"

    result = invoke("trial", "--help")
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "Technique family" in plain or "--family" in plain
    assert "Mad Hatter mutator" in plain or "--mutator" in plain


def recorded(db: Path) -> tuple[list[str], list[str]]:
    """The run's lines from the database and from its JSONL file."""
    with sqlite3.connect(db) as connection:
        [(run_id,)] = connection.execute("SELECT run_id FROM runs").fetchall()
        rows = connection.execute(
            "SELECT event_json FROM events WHERE run_id = ? ORDER BY seq", (run_id,)
        ).fetchall()
    jsonl = db.parent / "runs" / f"{run_id}.jsonl"
    return [row[0] for row in rows], jsonl.read_text(encoding="utf-8").splitlines()


def test_quick_mock_trial_runs_offline_and_records_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "out" / "court.db"
    result = invoke("trial", "--quick", "--mock", "--db", str(db))
    assert result.exit_code == 0, result.output
    assert "Skipping spotlighting: the spotlighting defense isn't built yet (#17)" in result.output
    assert "Off with her head!" in result.output
    assert "3 of 4 matches leaked" in result.output

    rows, lines = recorded(db)
    assert rows == lines and len(lines) > 0
    events = [parse_event(line) for line in lines]
    assert events[0].type == "run_started" and events[-1].type == "run_ended"
    assert not (tmp_path / ".court").exists()  # --db wins over the preset's path


def test_trial_without_court_yaml_points_at_mock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    result = invoke("trial")
    assert result.exit_code == 1
    assert "No court.yaml here" in result.output
    assert "court trial --quick --mock" in result.output


def test_mock_trial_uses_court_yaml_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "court.yaml").write_text(
        "target: ollama:llama3.1\n"
        "defenses: [input_filter]\n"
        "scenarios: [vault]\n"
        "max_turns: 2\n"
        "db_path: data/court.db\n",
        encoding="utf-8",
    )
    result = invoke("trial", "--mock", "--mode", "fixed", "--family", "role_play")
    assert result.exit_code == 0, result.output
    assert "0 of 1 matches leaked" in result.output
    _, lines = recorded(tmp_path / "data" / "court.db")
    [started] = [e for e in map(parse_event, lines) if isinstance(e, MatchStarted)]
    assert started.match.defense == "input_filter"
    assert started.match.family == "role_play"
    assert started.match.max_turns == 2


def test_trial_passes_mutators_into_the_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    result = invoke("trial", "--mock", "--mutator", "homoglyphs", "--mutator", "base64")
    assert result.exit_code == 0, result.output
    _, lines = recorded(tmp_path / ".court" / "court.db")
    started = [e for e in map(parse_event, lines) if isinstance(e, MatchStarted)]
    assert {tuple(e.match.enabled_mutators or []) for e in started} == {
        (MutatorId.HOMOGLYPHS, MutatorId.BASE64)
    }


def test_fixed_mode_without_a_family_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    result = invoke("trial", "--mock", "--mode", "fixed")
    assert result.exit_code == 2
    assert "--family" in result.output


@pytest.mark.parametrize(
    ("yaml", "message"),
    [
        ("target: llama3.1\ndefenses: ['plain!']\n", "bad defense name"),
        ("target: llama3.1\ndefenses: [plain+moat]\n", "unknown defense 'moat'"),
        ("target: 'python:my_agent:respond'\n", "agent target"),
    ],
)
def test_bad_court_yaml_is_a_usage_error(
    yaml: str, message: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "court.yaml").write_text(yaml, encoding="utf-8")
    result = invoke("trial")
    assert result.exit_code == 2
    assert message in result.output


def test_ci_rejects_a_budget_outside_zero_to_one() -> None:
    result = invoke("ci", "--fail-above", "1.5")
    assert result.exit_code == 2


def test_schema_prints_the_event_schema() -> None:
    result = invoke("schema")
    assert result.exit_code == 0
    assert "run_started" in json.loads(result.output)["discriminator"]["mapping"]
