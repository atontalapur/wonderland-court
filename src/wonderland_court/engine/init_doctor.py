"""`court init` and `court doctor`: get a laptop ready for a trial.

`court init` writes a five-line court.yaml that uses the models already installed in Ollama.
`court doctor` checks Python, SQLite WAL mode, Ollama and the four models from the dev setup
(#1), and with `--pull` runs `ollama pull` for the missing ones. Both read the installed models
from `/v1/models` at `OLLAMA_HOST` (default 127.0.0.1:11434), the OpenAI-compatible endpoint
Court's LLM client calls, so a passing check means the client will find the model too.

Each command makes one or two local requests with a short timeout, so neither goes through the
LLM client's rate limits. Doctor says whether API keys are set and never shows their values.
"""

import contextlib
import os
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
from rich.table import Table

from wonderland_court.config import CourtConfig
from wonderland_court.llm import ollama_base_url


def _default(field: str) -> str:
    return str(CourtConfig.model_fields[field].default)


JUDGE_MODEL = _default("judge_model")  # llama3.1, also the default target
ATTACKER_MODEL = _default("attacker_model")  # qwen3.5:4b
REQUIRED_MODELS: tuple[str, ...] = tuple(
    dict.fromkeys(
        _default(field) for field in ("judge_model", "attacker_model", "guard_model", "embed_model")
    )
)
API_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
TIMEOUT_S = 3.0
INSTALL_OLLAMA = "Install Ollama from https://ollama.com/download, then run `court doctor --pull`."


# Finding models


class OllamaUnreachable(RuntimeError):
    pass


def ollama_host() -> str:
    return ollama_base_url().removesuffix("/v1")


def list_ollama_models(timeout: float = TIMEOUT_S) -> list[str]:
    """Installed model names, such as `llama3.1:latest`."""
    try:
        response = httpx.get(f"{ollama_base_url()}/models", timeout=timeout)
        response.raise_for_status()
        return [str(item["id"]) for item in response.json()["data"]]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise OllamaUnreachable(
            f"can't reach Ollama at {ollama_host()} ({type(exc).__name__})"
        ) from exc


def _tagged(name: str) -> str:
    return name if ":" in name else f"{name}:latest"


def is_installed(model: str, installed: Sequence[str]) -> bool:
    """`llama3.1` means `llama3.1:latest` to Ollama, so `llama3.1:70b` doesn't count."""
    return _tagged(model) in {_tagged(name) for name in installed}


# court init


def pick_models(installed: Sequence[str] | None) -> tuple[str, str, str]:
    """The target, attacker and judge models: the defaults, or whichever of them is installed."""
    have = [m for m in (JUDGE_MODEL, ATTACKER_MODEL) if installed and is_installed(m, installed)]
    if not have:
        return JUDGE_MODEL, ATTACKER_MODEL, JUDGE_MODEL
    attacker = ATTACKER_MODEL if ATTACKER_MODEL in have else have[0]
    return have[0], attacker, have[0]


def court_yaml_text(installed: Sequence[str] | None) -> str:
    target, attacker, judge = pick_models(installed)
    return (
        "# Written by `court init`. Check your setup with `court doctor`, then run `court trial`.\n"
        f"target: ollama:{target}\n"
        "preset: quick  # first_blood, quick or full\n"
        f"attacker_model: {attacker}\n"
        f"judge_model: {judge}\n"
    )


def write_court_yaml(path: Path, installed: Sequence[str] | None, *, force: bool) -> str:
    """Write court.yaml and return its text. An existing file needs `force`."""
    if path.exists() and not force:
        raise FileExistsError(path)
    text = court_yaml_text(installed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


# court doctor


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str
    fix: str | None = None


def check_python(version: Sequence[int]) -> Check:
    shown = ".".join(str(part) for part in version)
    if tuple(version[:2]) >= (3, 11):
        return Check("Python", Status.PASS, f"Python {shown}")
    return Check(
        "Python",
        Status.FAIL,
        f"Python {shown}",
        "Use Python 3.11 or newer, for example `uv python install 3.12`.",
    )


def check_sqlite_wal() -> Check:
    try:
        with tempfile.TemporaryDirectory() as directory:
            connection = sqlite3.connect(Path(directory) / "wal-check.db")
            try:
                mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            finally:
                connection.close()
    except sqlite3.Error as exc:
        mode = f"error: {exc}"
    detail = f"SQLite {sqlite3.sqlite_version}, journal mode {mode}"
    if mode == "wal":
        return Check("SQLite WAL", Status.PASS, detail)
    fix = "Court's store needs WAL mode. Use a Python build with a standard SQLite."
    return Check("SQLite WAL", Status.FAIL, detail, fix)


def check_api_keys() -> Check:
    states = [f"{name} is {'set' if os.environ.get(name) else 'not set'}" for name in API_KEYS]
    detail = ", ".join(states) + ". Only openai: and anthropic: targets need them."
    return Check("API keys", Status.PASS, detail)


Runner = Callable[..., Any]


def pull_models(models: Sequence[str], runner: Runner) -> dict[str, tuple[str, str]]:
    """Run `ollama pull` for each model. Returns `(detail, fix)` for each one that failed."""
    failed: dict[str, tuple[str, str]] = {}
    for index, model in enumerate(models):
        try:
            result = runner(["ollama", "pull", model], check=False)
        except FileNotFoundError:
            for skipped in models[index:]:
                failed[skipped] = ("the ollama command isn't installed", INSTALL_OLLAMA)
            break
        if result.returncode != 0:
            failed[model] = (
                f"`ollama pull {model}` exited with {result.returncode}",
                f"Run `ollama pull {model}` and check its output.",
            )
    return failed


def run_doctor(
    *,
    pull: bool = False,
    python: Sequence[int] = tuple(sys.version_info[:3]),
    runner: Runner = subprocess.run,
) -> list[Check]:
    checks = [check_python(python), check_sqlite_wal()]
    host = ollama_host()
    try:
        installed = list_ollama_models()
    except OllamaUnreachable as exc:
        fix = (
            "Start Ollama with `ollama serve` or the Ollama app. If it runs on another machine, "
            f"set OLLAMA_HOST (now {host}). {INSTALL_OLLAMA}"
        )
        checks.append(Check("Ollama", Status.FAIL, str(exc), fix))
        checks += [Check(m, Status.SKIP, "Ollama isn't reachable") for m in REQUIRED_MODELS]
        return [*checks, check_api_keys()]
    checks.append(Check("Ollama", Status.PASS, f"reachable at {host}, {len(installed)} models"))

    failed: dict[str, tuple[str, str]] = {}
    missing = [m for m in REQUIRED_MODELS if not is_installed(m, installed)]
    if pull and missing:
        failed = pull_models(missing, runner)
        # If Ollama stopped mid-pull, keep the old list; those models still show as missing.
        with contextlib.suppress(OllamaUnreachable):
            installed = list_ollama_models()
    for model in REQUIRED_MODELS:
        if is_installed(model, installed):
            checks.append(Check(model, Status.PASS, "installed"))
        elif model in failed:
            checks.append(Check(model, Status.FAIL, *failed[model]))
        else:
            fix = f"Run `court doctor --pull`, or `ollama pull {model}`."
            checks.append(Check(model, Status.FAIL, "not installed", fix))
    return [*checks, check_api_keys()]


def doctor_ok(checks: Sequence[Check]) -> bool:
    return all(check.status != Status.FAIL for check in checks)


_STATUS_STYLE = {
    Status.PASS: "[green]ok[/green]",
    Status.FAIL: "[bold red]fail[/bold red]",
    Status.SKIP: "[dim]skipped[/dim]",
}


def doctor_table(checks: Sequence[Check]) -> Table:
    table = Table(title="court doctor")
    for column in ("Check", "Status", "Details", "Fix"):
        table.add_column(column)
    for check in checks:
        table.add_row(check.name, _STATUS_STYLE[check.status], check.detail, check.fix or "")
    return table
