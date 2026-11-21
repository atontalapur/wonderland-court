import json
import re
from typing import Any, cast

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from wonderland_court import __version__
from wonderland_court.cli import app
from wonderland_court.contracts import MutatorId, TechniqueFamily

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
