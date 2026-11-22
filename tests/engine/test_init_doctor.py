"""`court init` and `court doctor`, against respx and a fake `ollama` command. No network."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from rich.console import Console
from typer.testing import CliRunner, Result

from wonderland_court import cli
from wonderland_court.config import load_config
from wonderland_court.engine import init_doctor
from wonderland_court.engine.init_doctor import (
    REQUIRED_MODELS,
    Check,
    OllamaUnreachable,
    Status,
    doctor_ok,
    doctor_table,
    list_ollama_models,
    run_doctor,
    write_court_yaml,
)

MODELS_URL = "http://127.0.0.1:11434/v1/models"
ALL_MODELS = ["llama3.1:latest", "qwen3.5:4b", "llama-guard3:1b", "nomic-embed-text:latest"]


def models_response(names: Sequence[str]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": [
                {"id": name, "object": "model", "created": 1763700000, "owned_by": "library"}
                for name in names
            ],
        },
    )


@pytest.fixture(autouse=True)
def local_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)


# Finding models


@respx.mock
def test_models_come_from_the_v1_endpoint_court_calls() -> None:
    respx.get(MODELS_URL).mock(return_value=models_response(["llama3.1:latest", "qwen3.5:4b"]))
    assert list_ollama_models() == ["llama3.1:latest", "qwen3.5:4b"]


@respx.mock
def test_ollama_host_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "10.0.0.5:11434")
    respx.get("http://10.0.0.5:11434/v1/models").mock(return_value=models_response(["x:1"]))
    assert list_ollama_models() == ["x:1"]


@respx.mock
def test_an_unreachable_ollama_names_where_it_looked() -> None:
    respx.get(MODELS_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(OllamaUnreachable, match="127.0.0.1:11434"):
        list_ollama_models()


# court init


def test_init_writes_a_short_config_from_the_installed_models(tmp_path: Path) -> None:
    path = tmp_path / "court.yaml"
    write_court_yaml(path, ALL_MODELS, force=False)
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 5
    config = load_config(path)
    assert (config.target, config.attacker_model, config.judge_model) == (
        "ollama:llama3.1",
        "qwen3.5:4b",
        "llama3.1",
    )


def test_init_makes_do_with_qwen_alone(tmp_path: Path) -> None:
    path = tmp_path / "court.yaml"
    write_court_yaml(path, ["qwen3.5:4b"], force=False)
    config = load_config(path)
    assert (config.target, config.attacker_model, config.judge_model) == (
        "ollama:qwen3.5:4b",
        "qwen3.5:4b",
        "qwen3.5:4b",
    )


@pytest.mark.parametrize("installed", [None, [], ["llama3.1:70b", "mistral:latest"]])
def test_init_falls_back_to_the_defaults(tmp_path: Path, installed: list[str] | None) -> None:
    # `llama3.1` means `llama3.1:latest` to Ollama, so `llama3.1:70b` doesn't count.
    path = tmp_path / "court.yaml"
    write_court_yaml(path, installed, force=False)
    config = load_config(path)
    assert (config.target, config.attacker_model, config.judge_model) == (
        "ollama:llama3.1",
        "qwen3.5:4b",
        "llama3.1",
    )


def test_init_never_overwrites_without_force(tmp_path: Path) -> None:
    path = tmp_path / "court.yaml"
    path.write_text("target: openai:gpt-5\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_court_yaml(path, ALL_MODELS, force=False)
    assert path.read_text(encoding="utf-8") == "target: openai:gpt-5\n"
    write_court_yaml(path, ALL_MODELS, force=True)
    assert load_config(path).target == "ollama:llama3.1"


# court doctor


class FakeOllamaCLI:
    """Records `ollama pull` commands. `missing=True` acts as if Ollama isn't installed."""

    def __init__(self, *, missing: bool = False, returncode: int = 0) -> None:
        self.missing = missing
        self.returncode = returncode
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> Any:
        if self.missing:
            raise FileNotFoundError(command[0])
        self.commands.append(command)
        return type("Completed", (), {"returncode": self.returncode})()


def by_name(checks: list[Check]) -> dict[str, Check]:
    return {check.name: check for check in checks}


@respx.mock
def test_a_ready_laptop_passes_every_check() -> None:
    respx.get(MODELS_URL).mock(return_value=models_response(ALL_MODELS))
    checks = run_doctor(runner=FakeOllamaCLI())
    statuses = {check.name: check.status for check in checks}
    assert statuses["Python"] == Status.PASS
    assert statuses["SQLite WAL"] == Status.PASS
    assert statuses["Ollama"] == Status.PASS
    for model in REQUIRED_MODELS:
        assert statuses[model] == Status.PASS
    assert doctor_ok(checks)


def test_an_old_python_fails() -> None:
    with respx.mock:
        respx.get(MODELS_URL).mock(return_value=models_response(ALL_MODELS))
        checks = run_doctor(python=(3, 10, 14), runner=FakeOllamaCLI())
    python = by_name(checks)["Python"]
    assert python.status == Status.FAIL
    assert "3.11" in (python.fix or "")
    assert not doctor_ok(checks)


@respx.mock
def test_an_offline_ollama_explains_how_to_start_it_and_skips_the_models() -> None:
    respx.get(MODELS_URL).mock(side_effect=httpx.ConnectError("refused"))
    checks = by_name(run_doctor(runner=FakeOllamaCLI()))
    assert checks["Ollama"].status == Status.FAIL
    assert "ollama serve" in (checks["Ollama"].fix or "")
    assert "OLLAMA_HOST" in (checks["Ollama"].fix or "")
    for model in REQUIRED_MODELS:
        assert checks[model].status == Status.SKIP


@respx.mock
def test_missing_models_say_how_to_pull_them() -> None:
    respx.get(MODELS_URL).mock(return_value=models_response(["llama3.1:latest", "qwen3.5:4b"]))
    checks = by_name(run_doctor(runner=FakeOllamaCLI()))
    assert checks["llama-guard3:1b"].status == Status.FAIL
    assert "ollama pull llama-guard3:1b" in (checks["llama-guard3:1b"].fix or "")
    assert "--pull" in (checks["llama-guard3:1b"].fix or "")
    assert checks["llama3.1"].status == Status.PASS


@respx.mock
def test_pull_fetches_only_the_missing_models_then_checks_again() -> None:
    respx.get(MODELS_URL).mock(
        side_effect=[models_response(ALL_MODELS[:2]), models_response(ALL_MODELS)]
    )
    cli = FakeOllamaCLI()
    checks = run_doctor(pull=True, runner=cli)
    assert cli.commands == [
        ["ollama", "pull", "llama-guard3:1b"],
        ["ollama", "pull", "nomic-embed-text"],
    ]
    assert doctor_ok(checks)


@respx.mock
def test_pull_without_the_ollama_command_says_to_install_it() -> None:
    respx.get(MODELS_URL).mock(return_value=models_response(ALL_MODELS[:2]))
    checks = by_name(run_doctor(pull=True, runner=FakeOllamaCLI(missing=True)))
    assert checks["llama-guard3:1b"].status == Status.FAIL
    assert "ollama.com/download" in (checks["llama-guard3:1b"].fix or "")


@respx.mock
def test_a_failed_pull_is_reported() -> None:
    respx.get(MODELS_URL).mock(return_value=models_response(ALL_MODELS[:3]))
    checks = by_name(run_doctor(pull=True, runner=FakeOllamaCLI(returncode=1)))
    assert checks["nomic-embed-text"].status == Status.FAIL
    assert "ollama pull nomic-embed-text" in (checks["nomic-embed-text"].fix or "")


@respx.mock
def test_api_keys_are_reported_as_set_or_not_but_never_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-do-not-print")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    respx.get(MODELS_URL).mock(return_value=models_response(ALL_MODELS))
    checks = run_doctor(runner=FakeOllamaCLI())
    console = Console(record=True, width=200)
    console.print(doctor_table(checks))
    text = console.export_text()
    assert "sk-test-do-not-print" not in text
    assert "OPENAI_API_KEY is set" in text
    assert "ANTHROPIC_API_KEY is not set" in text


# The commands


def invoke(*args: str) -> Result:
    return CliRunner().invoke(cli.app, list(args), env={"COLUMNS": "200", "NO_COLOR": "1"})


@respx.mock
def test_court_init_writes_court_yaml_from_the_installed_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    respx.get(MODELS_URL).mock(return_value=models_response(["qwen3.5:4b"]))
    result = invoke("init")
    assert result.exit_code == 0, result.output
    assert "Wrote court.yaml" in result.output
    assert "court doctor" in result.output
    assert load_config(tmp_path / "court.yaml").target == "ollama:qwen3.5:4b"


@respx.mock
def test_court_init_uses_the_defaults_when_ollama_is_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    respx.get(MODELS_URL).mock(side_effect=httpx.ConnectError("refused"))
    result = invoke("init", "-c", "shop/court.yaml")
    assert result.exit_code == 0, result.output
    assert "can't reach Ollama at http://127.0.0.1:11434" in result.output
    assert "uses the default models" in result.output
    assert load_config(tmp_path / "shop" / "court.yaml").target == "ollama:llama3.1"


@respx.mock
def test_court_init_keeps_an_existing_court_yaml_unless_forced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    route = respx.get(MODELS_URL).mock(return_value=models_response(ALL_MODELS))
    (tmp_path / "court.yaml").write_text("target: openai:gpt-5\n", encoding="utf-8")
    refused = invoke("init")
    assert refused.exit_code == 1
    assert "court.yaml already exists. Pass --force" in refused.output
    assert not route.called  # it refuses before asking Ollama anything
    assert (tmp_path / "court.yaml").read_text(encoding="utf-8") == "target: openai:gpt-5\n"

    assert invoke("init", "--force").exit_code == 0
    assert load_config(tmp_path / "court.yaml").target == "ollama:llama3.1"


@respx.mock
def test_court_doctor_passes_on_a_ready_laptop_without_showing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-do-not-print")
    respx.get(MODELS_URL).mock(return_value=models_response(ALL_MODELS))
    result = invoke("doctor")
    assert result.exit_code == 0, result.output
    assert "court doctor" in result.output
    assert "Ready for `court trial`" in result.output
    assert "sk-test-do-not-print" not in result.output


@respx.mock
def test_court_doctor_fails_with_fixes_when_ollama_is_offline() -> None:
    respx.get(MODELS_URL).mock(side_effect=httpx.ConnectError("refused"))
    result = invoke("doctor")
    assert result.exit_code == 1
    assert "ollama serve" in result.output
    assert "skipped" in result.output
    assert "Some checks failed" in result.output
    assert "Traceback" not in result.output


@respx.mock
def test_court_doctor_pull_pulls_the_missing_models(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(MODELS_URL).mock(
        side_effect=[models_response(ALL_MODELS[:3]), models_response(ALL_MODELS)]
    )
    fake = FakeOllamaCLI()
    monkeypatch.setattr(
        cli, "run_doctor", lambda pull: init_doctor.run_doctor(pull=pull, runner=fake)
    )
    result = invoke("doctor", "--pull")
    assert result.exit_code == 0, result.output
    assert fake.commands == [["ollama", "pull", "nomic-embed-text"]]
