import json
import re
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from typer.main import get_command
from typer.testing import CliRunner, Result

from wonderland_court import __version__, cli, registry
from wonderland_court.cli import app
from wonderland_court.contracts import (
    MatchStarted,
    MutatorId,
    TargetKind,
    TargetReply,
    TargetRequest,
    TechniqueFamily,
    parse_event,
)

runner = CliRunner()
WIDE = {"COLUMNS": "200", "NO_COLOR": "1"}
FAKE_RUN = Path(__file__).resolve().parents[1] / "fixtures" / "fake_run.jsonl"

COMMANDS = ["init", "doctor", "trial", "serve", "report", "ci", "advise", "retrial"]
STUBS = ["ci", "retrial"]


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


def test_advise_says_when_the_caterpillar_is_not_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    component = registry.REMEDIATOR
    monkeypatch.setattr(
        registry, "load_remediator", lambda config, client: registry.NotBuilt(component)
    )
    result = invoke("advise")
    assert result.exit_code == 1
    assert f"{component.module} isn't built yet ({component.issue})" in result.output


def test_advise_reports_the_caterpillars_error_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    assert invoke("advise").output.startswith("No runs in .court/court.db yet")
    assert invoke("trial", "--mock").exit_code == 0
    result = invoke("advise")
    assert result.exit_code == 1
    assert result.output.startswith("court advise: ")
    assert "Traceback" not in result.output


# serve and report, from the Courtroom track (#42)


def test_serve_help_exposes_replay_and_db() -> None:
    root = cast(Any, get_command(app))
    serve_cmd = root.commands["serve"]
    opts = {opt for param in serve_cmd.params for opt in param.opts}
    assert {"--replay", "--speed", "--db", "--host", "--port", "--config"}.issubset(opts)

    result = invoke("serve", "--help")
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--replay" in plain
    assert "--speed" in plain
    assert "--db" in plain


@pytest.mark.parametrize("fmt", ["html", "md", "json", "sarif"])
def test_report_renders_all_formats_from_jsonl(fmt: str, tmp_path: Path) -> None:
    out_file = tmp_path / f"report.{fmt}"
    result = invoke("report", "--format", fmt, "--input", str(FAKE_RUN), "--out", str(out_file))
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


def tea_shop_config(root: Path) -> Path:
    """A court.yaml in a subfolder, like examples/tea_shop/court.yaml."""
    folder = root / "examples" / "tea_shop"
    folder.mkdir(parents=True)
    path = folder / "court.yaml"
    path.write_text("target: ollama:llama3.1\ndefenses: [plain]\nscenarios: [vault]\n")
    return path


def test_serve_reads_the_database_trial_writes_for_the_same_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from wonderland_court.courtroom import server

    monkeypatch.chdir(tmp_path)
    config = tea_shop_config(tmp_path)
    served: list[Path] = []
    monkeypatch.setattr(server, "run_server", lambda **kwargs: served.append(kwargs["db_path"]))

    trial = invoke("trial", "--mock", "-c", str(config.relative_to(tmp_path)))
    assert trial.exit_code == 0, trial.output
    written = Path("examples/tea_shop/.court/court.db")
    assert written.is_file()

    assert invoke("serve", "-c", "examples/tea_shop/court.yaml").exit_code == 0
    assert invoke("serve", "-c", "examples/tea_shop/court.yaml", "--db", "other.db").exit_code == 0
    assert served == [written, Path("other.db")]


def test_report_looks_for_the_configs_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    tea_shop_config(tmp_path)
    missing = invoke("report", "-c", "examples/tea_shop/court.yaml", "--format", "json")
    assert missing.exit_code == 1
    assert "No database found at examples/tea_shop/.court/court.db" in missing.output

    assert invoke("trial", "--mock", "-c", "examples/tea_shop/court.yaml").exit_code == 0
    out = tmp_path / "report.json"
    found = invoke(
        "report", "-c", "examples/tea_shop/court.yaml", "--format", "json", "--out", str(out)
    )
    assert found.exit_code == 0, found.output
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["run_id"].startswith("run-")


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
        ("target: llama3.1\ndefenses: [plain, spotlighting+moat]\n", "unknown defense 'moat'"),
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


@pytest.mark.parametrize("args", [["trial", "--mock"], ["advise"], ["report"], ["serve"]])
def test_an_explicit_config_that_is_missing_is_a_usage_error(
    args: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    result = invoke(*args, "--config", "prod.yml")
    assert result.exit_code == 2
    assert "prod.yml doesn't exist" in result.output


def test_a_real_trial_that_fails_says_why_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Unreachable:
        name = "ollama:llama3.1"
        kind = TargetKind.MODEL

        async def respond(self, request: TargetRequest) -> TargetReply:
            raise ConnectionError("Ollama isn't answering on 127.0.0.1:11434")

    monkeypatch.chdir(tmp_path)
    (tmp_path / "court.yaml").write_text(
        "target: ollama:llama3.1\ndefenses: [plain]\nscenarios: [vault]\n", encoding="utf-8"
    )
    monkeypatch.setattr(cli, "build_target", lambda spec, client: Unreachable())
    monkeypatch.setattr(registry, "load_attacker", lambda c, client: registry.ScriptedAttacker())
    monkeypatch.setattr(registry, "load_judge", lambda c, client: registry.CanaryJudge())
    result = invoke("trial")
    assert result.exit_code == 1
    assert "The trial stopped: ConnectionError: Ollama isn't answering" in result.output
    assert "Traceback" not in result.output
    with sqlite3.connect(tmp_path / ".court" / "court.db") as connection:
        assert connection.execute("SELECT status FROM runs").fetchall() == [("failed",)]


def test_ci_rejects_a_budget_outside_zero_to_one() -> None:
    result = invoke("ci", "--fail-above", "1.5")
    assert result.exit_code == 2


def test_schema_prints_the_event_schema() -> None:
    result = invoke("schema")
    assert result.exit_code == 0
    assert "run_started" in json.loads(result.output)["discriminator"]["mapping"]
