import json

import pytest
from typer.testing import CliRunner

from wonderland_court import __version__
from wonderland_court.cli import app

runner = CliRunner()

STUBS = ["init", "doctor", "trial", "serve", "report", "ci", "advise", "retrial"]


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in STUBS:
        assert command in result.output


@pytest.mark.parametrize("command", STUBS)
def test_stubs_fail_until_built(command: str) -> None:
    result = runner.invoke(app, [command])
    assert result.exit_code == 1
    assert "isn't built yet" in result.output


def test_ci_rejects_a_budget_outside_zero_to_one() -> None:
    result = runner.invoke(app, ["ci", "--fail-above", "1.5"])
    assert result.exit_code == 2


def test_schema_prints_the_event_schema() -> None:
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    assert "run_started" in json.loads(result.output)["discriminator"]["mapping"]
