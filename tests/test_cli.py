import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from wonderland_court import __version__
from wonderland_court.cli import app
from wonderland_court.contracts import MutatorId, TechniqueFamily

runner = CliRunner()

BUILT_COMMANDS = ["serve", "report"]
STUBS = ["init", "doctor", "trial", "ci", "advise", "retrial"]
FAKE_RUN = Path(__file__).resolve().parents[1] / "fixtures" / "fake_run.jsonl"


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in [*BUILT_COMMANDS, *STUBS]:
        assert command in result.output


@pytest.mark.parametrize("command", STUBS)
def test_stubs_fail_until_built(command: str) -> None:
    result = runner.invoke(app, [command])
    assert result.exit_code == 1
    assert "isn't built yet" in result.output


def test_serve_help_exposes_replay_and_db() -> None:
    root = cast(Any, get_command(app))
    serve_cmd = root.commands["serve"]
    opts = {opt for param in serve_cmd.params for opt in param.opts}
    assert {"--replay", "--speed", "--db", "--host", "--port"}.issubset(opts)

    result = runner.invoke(app, ["serve", "--help"], env={"COLUMNS": "200", "NO_COLOR": "1"})
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--replay" in plain
    assert "--speed" in plain
    assert "--db" in plain


@pytest.mark.parametrize("fmt", ["html", "md", "json", "sarif"])
def test_report_renders_all_formats_from_jsonl(fmt: str, tmp_path: Path) -> None:
    out_file = tmp_path / f"report.{fmt}"
    result = runner.invoke(
        app,
        ["report", "--format", fmt, "--input", str(FAKE_RUN), "--out", str(out_file)],
    )
    assert result.exit_code == 0, result.output
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    if fmt == "sarif":
        parsed = json.loads(content)
        assert parsed["version"] == "2.1.0"
        assert parsed["runs"][0]["results"]
    elif fmt == "json":
        parsed = json.loads(content)
        assert parsed["summary"]["run_id"] == "fake-run-0001"
    elif fmt == "html":
        assert "<!DOCTYPE html>" in content or "<html" in content.lower()
        assert "fake-run-0001" in content
    else:
        assert "fake-run-0001" in content


def test_report_reads_from_db_and_errors_without_default_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from wonderland_court.contracts import dump_event, read_events
    from wonderland_court.courtroom.db_reader import COURT_SCHEMA_SQL

    monkeypatch.chdir(tmp_path)
    missing_res = runner.invoke(app, ["report", "--format", "json"])
    assert missing_res.exit_code == 1
    assert ".court/court.db" in missing_res.output

    db_path = tmp_path / "custom.db"
    events = list(read_events(FAKE_RUN))
    with sqlite3.connect(db_path) as conn:
        conn.executescript(COURT_SCHEMA_SQL)
        for ev in events:
            conn.execute(
                "INSERT INTO events (seq, run_id, ts, type, event_json) VALUES (?, ?, ?, ?, ?)",
                (ev.seq, ev.run_id, ev.ts.isoformat(), ev.type, dump_event(ev)),
            )
        conn.commit()

    out_json = tmp_path / "db_report.json"
    db_res = runner.invoke(
        app,
        ["report", "--format", "json", "--db", str(db_path), "--out", str(out_json)],
    )
    assert db_res.exit_code == 0, db_res.output
    assert json.loads(out_json.read_text(encoding="utf-8"))["summary"]["run_id"] == "fake-run-0001"


def test_trial_exposes_selectable_tactics() -> None:
    """Rich help truncates on narrow CI terminals, so assert on the Click params."""
    root = cast(Any, get_command(app))
    trial = root.commands["trial"]
    opts = {opt: param for param in trial.params for opt in param.opts}
    assert "--family" in opts
    assert "--mutator" in opts
    family_help = opts["--family"].help or ""
    mutator_help = opts["--mutator"].help or ""
    assert "Technique family" in family_help
    assert "Mad Hatter mutator" in mutator_help
    assert TechniqueFamily.FOOT_IN_THE_DOOR.value == "foot_in_the_door"
    assert MutatorId.LOW_RESOURCE_LANGUAGE.value == "low_resource_language"

    result = runner.invoke(app, ["trial", "--help"], env={"COLUMNS": "200", "NO_COLOR": "1"})
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "Technique family" in plain or "--family" in plain
    assert "Mad Hatter mutator" in plain or "--mutator" in plain


def test_ci_rejects_a_budget_outside_zero_to_one() -> None:
    result = runner.invoke(app, ["ci", "--fail-above", "1.5"])
    assert result.exit_code == 2


def test_schema_prints_the_event_schema() -> None:
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    assert "run_started" in json.loads(result.output)["discriminator"]["mapping"]
