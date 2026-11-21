from pathlib import Path

import pytest

from wonderland_court.config import (
    PRESETS,
    ConfigError,
    CourtConfig,
    HttpTargetConfig,
    load_config,
)
from wonderland_court.contracts import MatchMode, ScenarioId


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
