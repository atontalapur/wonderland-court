"""The `court` command line. Each stub names the track that builds it."""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from wonderland_court import __version__
from wonderland_court.contracts import MatchMode, MutatorId, TechniqueFamily, event_json_schema

app = typer.Typer(
    name="court",
    help="Put your AI agent on trial.",
    no_args_is_help=True,
    add_completion=False,
)

ConfigOption = Annotated[Path, typer.Option("--config", "-c", help="Path to court.yaml.")]
DEFAULT_CONFIG = Path("court.yaml")


class ReportFormat(StrEnum):
    HTML = "html"
    MD = "md"
    JSON = "json"
    SARIF = "sarif"


def _not_built(command: str, track: str) -> NoReturn:
    typer.echo(f"court {command} isn't built yet ({track} track).", err=True)
    raise typer.Exit(code=1)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"court {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_print_version, is_eager=True, help="Show the version."),
    ] = None,
) -> None:
    """Put your AI agent on trial."""


@app.command()
def init(
    force: Annotated[bool, typer.Option(help="Overwrite an existing court.yaml.")] = False,
) -> None:
    """Write court.yaml and find your Ollama models."""
    _not_built("init", "Engine")


@app.command()
def doctor() -> None:
    """Check Ollama and pull the judge and guard models."""
    _not_built("doctor", "Engine")


@app.command()
def trial(
    config: ConfigOption = DEFAULT_CONFIG,
    mode: Annotated[MatchMode, typer.Option(help="Fixed or adaptive attacker.")] = (
        MatchMode.ADAPTIVE
    ),
    family: Annotated[
        list[TechniqueFamily] | None,
        typer.Option(
            "--family",
            help=(
                "Technique family the Cheshire Cat may use (repeatable). "
                "Omit for the full default catalog, including research tactics."
            ),
        ),
    ] = None,
    mutator: Annotated[
        list[MutatorId] | None,
        typer.Option(
            "--mutator",
            help="Mad Hatter mutator allowed this run (repeatable). Omit for all defaults.",
        ),
    ] = None,
    quick: Annotated[bool, typer.Option(help="Small preset for slow laptops and demos.")] = False,
) -> None:
    """Run the tournament, live in the terminal."""
    # family/mutator are part of the public selection surface; Engine wires them into MatchSpec.
    _ = (family, mutator)
    _not_built("trial", "Engine")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to bind. Localhost by default.")] = (
        "127.0.0.1"
    ),
    port: Annotated[int, typer.Option(help="Port for the Courtroom.")] = 8000,
    replay: Annotated[
        Path | None, typer.Option(help="Replay a recorded run file instead of a live run.")
    ] = None,
    speed: Annotated[float, typer.Option(help="Replay speed multiplier.")] = 4.0,
) -> None:
    """Open the Courtroom dashboard."""
    _not_built("serve", "Courtroom")


@app.command()
def report(
    format: Annotated[ReportFormat, typer.Option("--format", "-f", help="Output format.")] = (
        ReportFormat.HTML
    ),
    run: Annotated[str | None, typer.Option(help="Run id. Defaults to the latest run.")] = None,
    out: Annotated[Path | None, typer.Option(help="Write to this file instead of stdout.")] = None,
) -> None:
    """Write a report for a finished run."""
    _not_built("report", "Courtroom")


@app.command()
def ci(
    config: ConfigOption = DEFAULT_CONFIG,
    fail_above: Annotated[
        float, typer.Option(help="Fail when attack success is above this share.", min=0, max=1)
    ] = 0.10,
) -> None:
    """Run a trial and fail the build when attack success is over budget."""
    _not_built("ci", "Engine")


@app.command()
def advise(
    run: Annotated[str | None, typer.Option(help="Run id. Defaults to the latest run.")] = None,
) -> None:
    """Advice from a Caterpillar: group failures and write a hardened config."""
    _not_built("advise", "Adversaries")


@app.command()
def retrial(
    run: Annotated[str | None, typer.Option(help="Run id. Defaults to the latest run.")] = None,
) -> None:
    """Re-run the same seeds against the hardened config."""
    _not_built("retrial", "Adversaries")


@app.command(hidden=True)
def schema() -> None:
    """Print the event JSON Schema, for generating the Courtroom's TypeScript types."""
    typer.echo(json.dumps(event_json_schema(), indent=2))
