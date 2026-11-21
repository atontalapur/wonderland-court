import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from wonderland_court.config import (
    PRESETS,
    ConfigError,
    CourtConfig,
    HttpTargetConfig,
    load_config,
)
from wonderland_court.contracts import (
    MatchMode,
    ScenarioId,
    dump_event,
    parse_event,
    read_events,
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "court.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# court.yaml


def test_a_one_line_config_uses_the_quick_preset(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, "target: ollama:llama3.1\n"))
    assert config.target == "ollama:llama3.1"
    assert config.preset == "quick"
    assert config.defenses == PRESETS["quick"]["defenses"]
    assert config.scenarios == [ScenarioId.VAULT, ScenarioId.REFUND_TOOL]
    assert config.attacker_model == "qwen3.5:4b"


def test_file_values_win_over_the_preset(tmp_path: Path) -> None:
    path = write(tmp_path, "target: ollama:llama3.1\npreset: full\nrounds: 1\nmode: fixed\n")
    config = load_config(path)
    assert config.rounds == 1
    assert config.mode is MatchMode.FIXED
    assert config.scenarios == PRESETS["full"]["scenarios"]


def test_a_preset_argument_replaces_the_file_preset(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, "target: ollama:llama3.1\npreset: full\n"), "first_blood")
    assert config.preset == "first_blood"
    assert config.defenses == ["plain"]


@pytest.mark.parametrize("name", list(PRESETS))
def test_every_preset_is_valid(name: str) -> None:
    config = CourtConfig.from_mapping({"target": "ollama:llama3.1"}, name)  # type: ignore[arg-type]
    assert config.preset == name


def test_http_and_python_targets_parse(tmp_path: Path) -> None:
    http = load_config(
        write(
            tmp_path,
            "target:\n  kind: http\n  url: http://localhost:9000/chat\n"
            "  request_template: {message: '{{message}}'}\n",
        )
    )
    assert isinstance(http.target, HttpTargetConfig)
    python = load_config(write(tmp_path, "target: python:my_pkg.agent:respond\n"))
    assert python.target == "python:my_pkg.agent:respond"


def test_db_path_is_relative_to_the_config_file(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, "target: ollama:llama3.1\n"))
    assert config.db_path == tmp_path / ".court" / "court.db"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("target: ollama:llama3.1\ndefense: [plain]\n", "defense"),
        ("target: ollama:llama3.1\nscenarios: [vault, teapot]\n", "scenarios"),
        ("target: ollama:llama3.1\ndefenses: [plain, plain]\n", "only be listed once"),
        ("target: ollama:llama3.1\ndefenses: ['guard+ ']\n", "bad defense name"),
        ("target: ollama:llama3.1\npreset: slow\n", "unknown preset"),
        ("rounds: 1\n", "target"),
        ("- just\n- a list\n", "mapping"),
        ("target: [unclosed\n", "can't read"),
    ],
)
def test_bad_configs_name_the_file_and_the_problem(
    tmp_path: Path, text: str, expected: str
) -> None:
    with pytest.raises(ConfigError, match=expected) as caught:
        load_config(write(tmp_path, text))
    assert "court.yaml" in str(caught.value)


# engine/schema.sql

SCHEMA = files("wonderland_court.engine").joinpath("schema.sql").read_text(encoding="utf-8")
TABLES = {
    "runs",
    "events",
    "matches",
    "standings",
    "utility_results",
    "judge_calibration",
    "remediation_advice",
    "retrial_comparisons",
    "llm_cache",
}


def table_names(db: sqlite3.Connection) -> set[str]:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {name for (name,) in rows}


def test_schema_creates_all_nine_tables_and_can_be_reapplied() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    db.executescript(SCHEMA)
    assert table_names(db) == TABLES
    assert db.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_schema_turns_on_wal_for_a_file_database(tmp_path: Path) -> None:
    db = sqlite3.connect(tmp_path / "court.db")
    db.executescript(SCHEMA)
    assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    db.close()


def test_events_table_round_trips_the_fake_run() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    events = list(read_events(Path(__file__).parents[1] / "fixtures" / "fake_run.jsonl"))
    db.executemany(
        "INSERT INTO events (seq, run_id, ts, type, event_json) VALUES (?, ?, ?, ?, ?)",
        [(e.seq, e.run_id, e.ts.isoformat(), e.type, dump_event(e)) for e in events],
    )
    stored = db.execute("SELECT event_json FROM events ORDER BY run_id, seq").fetchall()
    assert [parse_event(line) for (line,) in stored] == events
