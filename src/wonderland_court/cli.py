"""The `court` command line.

`court trial` runs here. `serve`, `report` and `advise` reach their track's code through the
registry, so those tracks never edit this file; until a track lands, its command says so and
exits 1. The remaining stubs name the issue that builds them.
"""

import asyncio
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress
from rich.table import Table

from wonderland_court import __version__, registry
from wonderland_court.config import ConfigError, CourtConfig, PresetName, load_config
from wonderland_court.contracts import (
    Attacker,
    Event,
    Judge,
    MatchEnded,
    MatchMode,
    MatchSpec,
    MatchStarted,
    MutatorId,
    Target,
    TargetKind,
    TechniqueFamily,
    event_json_schema,
)
from wonderland_court.engine.cache import SQLiteResponseCache
from wonderland_court.engine.defenses import parse_defenses
from wonderland_court.engine.mock import MockTarget
from wonderland_court.engine.runner import TrialResult, plan_matches, run_trial
from wonderland_court.engine.store import (
    CourtReader,
    CourtStore,
    RemediationAdvice,
    RunRecord,
)
from wonderland_court.engine.targets import build_target, canonical_spec
from wonderland_court.llm import RateLimitedLLMClient, default_client, set_default_client

app = typer.Typer(
    name="court",
    help="Put your AI agent on trial.",
    no_args_is_help=True,
    add_completion=False,
)

ConfigOption = Annotated[Path, typer.Option("--config", "-c", help="Path to court.yaml.")]
DEFAULT_CONFIG = Path("court.yaml")
DEFAULT_TARGET = "ollama:llama3.1"


class ReportFormat(StrEnum):
    HTML = "html"
    MD = "md"
    JSON = "json"
    SARIF = "sarif"


def _fail(message: str, code: int = 1) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def _not_built(command: str, track: str) -> NoReturn:
    _fail(f"court {command} isn't built yet ({track} track).")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"court {__version__}")
        raise typer.Exit()


def _missing(path: Path) -> None:
    """An explicit --config that isn't there is a typo, not a request for the defaults."""
    if path != DEFAULT_CONFIG:
        _fail(f"{path} doesn't exist.", code=2)


def _settings(path: Path, preset: PresetName | None = None) -> CourtConfig:
    """court.yaml if it exists, else the defaults with the default target."""
    if not path.exists():
        _missing(path)
        return CourtConfig.from_mapping({"target": DEFAULT_TARGET}, preset)
    try:
        return load_config(path, preset)
    except ConfigError as exc:
        _fail(str(exc), code=2)


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
    _not_built("init", "Engine, #19")


@app.command()
def doctor() -> None:
    """Check Ollama and pull the judge and guard models."""
    _not_built("doctor", "Engine, #19")


# court trial


def _trial_settings(path: Path, *, quick: bool, mock: bool) -> CourtConfig:
    preset: PresetName | None = "quick" if quick else None
    if path.exists():
        return _settings(path, preset)
    _missing(path)
    if not mock:
        _fail(
            f"No {path} here. Write one (court init arrives with #19), or try an offline "
            "run with `court trial --quick --mock`."
        )
    return CourtConfig.from_mapping({"target": MockTarget.name}, preset)


def _runnable_defenses(stacks: list[str], kind: TargetKind, console: Console) -> list[str]:
    """The stacks that can run today. Stacks naming a defense that isn't built are skipped."""
    runnable = []
    for stack in stacks:
        try:
            parse_defenses(stack, kind)
        except registry.NotBuiltError as exc:
            console.print(f"[yellow]Skipping {escape(stack)}: {escape(str(exc))}.[/]")
            continue
        except ValueError as exc:
            _fail(str(exc), code=2)
        runnable.append(stack)
    if not runnable:
        _fail("None of the configured defense stacks can run yet.")
    return runnable


class _Reporter:
    """One line per finished match, and a progress bar on a terminal."""

    def __init__(self, progress: Progress, total: int) -> None:
        self._progress = progress
        self._task = progress.add_task("Trial", total=total)
        self._specs: dict[str, MatchSpec] = {}

    def __call__(self, event: Event) -> None:
        if isinstance(event, MatchStarted):
            self._specs[event.match.match_id] = event.match
        elif isinstance(event, MatchEnded):
            spec = self._specs[event.match_id]
            label = escape(f"{spec.match_id}  {spec.defense} vs {spec.scenario.value}")
            if event.broken:
                verdict = (
                    f"[bold red]Off with her head![/] turn {event.broken_on_turn}, "
                    f"{escape(event.breaking_family or '')}"
                )
            else:
                verdict = f"[green]held[/] for {event.turns} turns"
            self._progress.console.print(f"{label}: {verdict}")
            self._progress.advance(self._task)


async def _trial(
    settings: CourtConfig,
    *,
    mock: bool,
    defenses: list[str],
    families: list[TechniqueFamily],
    mutators: list[MutatorId],
    console: Console,
    total: int,
) -> tuple[TrialResult, Path]:
    jsonl_dir = settings.db_path.parent / "runs"
    async with CourtStore(settings.db_path, jsonl_dir=jsonl_dir) as store:
        target: Target
        attacker: Attacker
        judge: Judge
        if mock:
            target, attacker, judge = (
                MockTarget(),
                registry.ScriptedAttacker(),
                registry.CanaryJudge(),
            )
        else:
            assert isinstance(settings.target, str)
            client = RateLimitedLLMClient(cache=SQLiteResponseCache(store))
            set_default_client(client)
            target = build_target(settings.target, client)
            attacker = registry.load_attacker(settings, client)
            judge = registry.load_judge(settings, client)
        with Progress(console=console, transient=True) as progress:
            result = await run_trial(
                settings,
                target=target,
                attacker=attacker,
                judge=judge,
                store=store,
                defenses=defenses,
                families=families,
                mutators=mutators,
                on_event=_Reporter(progress, total),
            )
    return result, jsonl_dir / f"{result.run_id}.jsonl"


@app.command()
def trial(
    config: ConfigOption = DEFAULT_CONFIG,
    mode: Annotated[
        MatchMode | None,
        typer.Option(help="Fixed or adaptive attacker. Defaults to court.yaml's mode."),
    ] = None,
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
    mock: Annotated[
        bool,
        typer.Option(help="Run offline: a scripted Alice, attacker and judge, no models."),
    ] = False,
    db: Annotated[
        Path | None, typer.Option(help="SQLite file to record the run in. Overrides court.yaml.")
    ] = None,
) -> None:
    """Run the tournament, live in the terminal."""
    console = Console()
    settings = _trial_settings(config, quick=quick, mock=mock)
    updates: dict[str, object] = {}
    if mode is not None:
        updates["mode"] = mode
    if db is not None:
        updates["db_path"] = db
    settings = settings.model_copy(update=updates)
    families, mutators = family or [], mutator or []

    if mock:
        name = MockTarget.name
    elif not isinstance(settings.target, str):
        _fail("HTTP and Python agent targets arrive with #19. Use a model target for now.")
    else:
        try:
            name = canonical_spec(settings.target)
        except ValueError as exc:
            _fail(str(exc), code=2)
    kind = TargetKind.MODEL  # agent targets arrive with #19
    defenses = _runnable_defenses(settings.defenses, kind, console)
    try:
        planned = plan_matches(
            settings,
            target=name,
            target_kind=kind,
            attacker="",
            defenses=defenses,
            families=families,
        )
    except ValueError as exc:
        _fail(str(exc), code=2)

    where = "offline, mock" if mock else name
    console.print(f"[bold]Wonderland Court[/] is in session: {len(planned)} matches ({where}).")
    try:
        result, jsonl = asyncio.run(
            _trial(
                settings,
                mock=mock,
                defenses=defenses,
                families=families,
                mutators=mutators,
                console=console,
                total=len(planned),
            )
        )
    except Exception as exc:
        if mock:
            raise  # nothing outside Court runs in a mock trial, so this is a bug: keep the trace
        _fail(
            f"The trial stopped: {type(exc).__name__}: {exc}\n"
            f"The run is marked failed in {settings.db_path}. Check that Ollama is running and "
            "the models are pulled (`ollama list`); `court doctor` will check this (#19)."
        )
    console.print(
        f"\n{result.leaks} of {len(result.matches)} matches leaked. Run [bold]{result.run_id}[/]"
    )
    console.print(escape(f"Recorded in {settings.db_path} and {jsonl}"))


# Commands other tracks build, reached through the registry


DbOption = Annotated[
    Path | None,
    typer.Option(
        help="SQLite database to read. Defaults to court.yaml's db_path (.court/court.db)."
    ),
]


def _db_path(db: Path | None, config: Path) -> Path:
    """--db, else the database `court trial -c <config>` writes, which court.yaml resolves
    relative to its own folder."""
    return db if db is not None else _settings(config).db_path


@app.command()
def serve(
    config: ConfigOption = DEFAULT_CONFIG,
    host: Annotated[str, typer.Option(help="Interface to bind. Localhost by default.")] = (
        "127.0.0.1"
    ),
    port: Annotated[int, typer.Option(help="Port for the Courtroom.")] = 8000,
    replay: Annotated[
        Path | None, typer.Option(help="Replay a recorded run file instead of a live run.")
    ] = None,
    speed: Annotated[float, typer.Option(min=0.1, help="Replay speed multiplier.")] = 4.0,
    db: DbOption = None,
) -> None:
    """Open the Courtroom dashboard."""
    from wonderland_court.courtroom.server import run_server

    run_server(host=host, port=port, replay=replay, speed=speed, db_path=_db_path(db, config))


@app.command()
def report(
    config: ConfigOption = DEFAULT_CONFIG,
    format: Annotated[ReportFormat, typer.Option("--format", "-f", help="Output format.")] = (
        ReportFormat.HTML
    ),
    run: Annotated[str | None, typer.Option(help="Run id. Defaults to the latest run.")] = None,
    out: Annotated[Path | None, typer.Option(help="Write to this file instead of stdout.")] = None,
    db: DbOption = None,
    input: Annotated[
        Path | None, typer.Option("--input", "-i", help="Read events from a JSONL file.")
    ] = None,
) -> None:
    """Write a report for a finished run."""
    from wonderland_court.courtroom.reports import write_report

    resolved_db = db
    if input is None:
        resolved_db = _db_path(db, config)
        if db is None and not resolved_db.is_file():
            _fail(f"No database found at {resolved_db}; pass --db <path> or --input <run.jsonl>.")

    try:
        rendered = write_report(
            fmt=format.value,
            out_path=out,
            db_path=resolved_db,
            input_path=input,
            run_id=run,
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"Report error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if out is None:
        typer.echo(rendered)
    else:
        typer.echo(f"Wrote {format.value.upper()} report to {out}")


@app.command()
def ci(
    config: ConfigOption = DEFAULT_CONFIG,
    fail_above: Annotated[
        float, typer.Option(help="Fail when attack success is above this share.", min=0, max=1)
    ] = 0.10,
) -> None:
    """Run a trial and fail the build when attack success is over budget."""
    _not_built("ci", "Engine, #26")


# court advise and court retrial, from the Adversaries track (#24)


HARDENED_NAME = "court.hardened.yaml"
HardenedOption = Annotated[
    Path | None,
    typer.Option(help=f"The hardened config. Defaults to {HARDENED_NAME} next to court.yaml."),
]
CHECK_MODELS = "Check that Ollama is running and the models are pulled (`ollama list`)."


async def _find_run(db_path: Path, run_id: str | None, *, retrials: bool) -> RunRecord | None:
    """Run `run_id`, else the latest run, skipping retrials unless `retrials` is set. `None`
    when the database or the run isn't there."""
    if not db_path.is_file():
        return None
    async with CourtReader(db_path) as reader:
        if run_id is not None:
            return await reader.get_run(run_id)
        runs = await reader.list_runs()
    return next((r for r in runs if retrials or r.parent_run_id is None), None)


def _run_or_fail(db_path: Path, run_id: str | None, *, retrials: bool = True) -> RunRecord:
    found = asyncio.run(_find_run(db_path, run_id, retrials=retrials))
    if found is not None:
        return found
    if run_id is not None:
        _fail(f"No run {run_id} in {db_path}.")
    _fail(f"No runs in {db_path} yet. Run `court trial` first.")


def _remediator(settings: CourtConfig, command: str) -> registry.Remediator:
    remediator = registry.load_remediator(settings, default_client())
    if isinstance(remediator, registry.NotBuilt):
        component = registry.REMEDIATOR
        _fail(f"court {command}: {component.module} isn't built yet ({component.issue})")
    return remediator


def _hardened_path(hardened: Path | None, config: Path) -> Path:
    return hardened if hardened is not None else config.parent / HARDENED_NAME


def _print_advice(
    console: Console, advice: RemediationAdvice, run: RunRecord, hardened: Path
) -> None:
    if advice.clusters:
        table = Table(title=escape(f"Failure families in run {advice.run_id}"))
        for column in ("Cluster", "Family", "Technique", "Scenario", "Matches", "Root cause"):
            table.add_column(column)
        for cluster in advice.clusters:
            table.add_row(
                *(
                    escape(str(cluster[key]))
                    for key in (
                        "cluster_id",
                        "family_label",
                        "technique_family",
                        "scenario",
                        "count",
                        "root_cause_summary",
                    )
                )
            )
        console.print(table)
    else:
        console.print(escape(f"No matches broke in run {advice.run_id}."))

    tried = ", ".join(run.config.get("defenses", []))
    console.print(f"\nRecommended defense: [bold]{escape(advice.recommended_defense)}[/]")
    console.print(escape(advice.rationale))
    console.print(f"[red]{escape(f'- defenses: {tried}')}[/]")
    console.print(f"[green]{escape(f'+ defenses: {advice.recommended_defense}')}[/]")
    try:
        parse_defenses(advice.recommended_defense, advice.target_kind)
    except registry.NotBuiltError as exc:
        console.print(
            f"[yellow]Note: {escape(str(exc))}, so `court retrial` can't run this stack yet. Edit "
            f"{escape(str(hardened))} to a stack that runs today.[/]"
        )
    console.print(escape(f"\nWrote {hardened}. Next: `court retrial` replays the same seeds."))


@app.command()
def advise(
    config: ConfigOption = DEFAULT_CONFIG,
    run: Annotated[str | None, typer.Option(help="Run id. Defaults to the latest run.")] = None,
    hardened: HardenedOption = None,
    db: DbOption = None,
) -> None:
    """Advice from a Caterpillar: group failures and write a hardened config."""
    remediator = _remediator(_settings(config), "advise")
    db_path = _db_path(db, config)
    record = _run_or_fail(db_path, run)
    path = _hardened_path(hardened, config)
    try:
        advice = asyncio.run(remediator.advise(db_path, record.run_id, hardened_path=path))
    except (LookupError, ValueError) as exc:
        _fail(f"court advise: {exc}")
    except Exception as exc:
        if record.target == MockTarget.name:
            raise  # a mock run's advice uses no model, so this is a bug: keep the trace
        _fail(f"court advise stopped: {type(exc).__name__}: {exc}\n{CHECK_MODELS}")
    _print_advice(Console(), advice, record, path)


@app.command()
def retrial(
    run: Annotated[str | None, typer.Option(help="Run id. Defaults to the latest run.")] = None,
) -> None:
    """Re-run the same seeds against the hardened config."""
    _not_built("retrial", "Adversaries, #24")


@app.command(hidden=True)
def schema() -> None:
    """Print the event JSON Schema, for generating the Courtroom's TypeScript types."""
    typer.echo(json.dumps(event_json_schema(), indent=2))
