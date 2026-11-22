"""The `court` command line.

`court trial` runs here. `serve`, `report`, `advise` and `retrial` reach their track's code
through the registry, so those tracks never edit this file; until a track lands, its command
says so and exits 1. The remaining stubs name the issue that builds them.
"""

import asyncio
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer
import yaml
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
from wonderland_court.engine.init_doctor import (
    OllamaUnreachable,
    doctor_ok,
    doctor_table,
    list_ollama_models,
    run_doctor,
    write_court_yaml,
)
from wonderland_court.engine.mock import MockTarget
from wonderland_court.engine.runner import TrialResult, plan_matches, run_trial
from wonderland_court.engine.store import (
    CourtReader,
    CourtStore,
    RemediationAdvice,
    RetrialComparison,
    RunRecord,
)
from wonderland_court.engine.targets import build_target, canonical_spec, is_agent_target
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
    config: ConfigOption = DEFAULT_CONFIG,
    force: Annotated[bool, typer.Option(help="Overwrite an existing court.yaml.")] = False,
) -> None:
    """Write court.yaml and find your Ollama models."""
    if config.exists() and not force:
        _fail(f"{config} already exists. Pass --force to overwrite it.")
    installed: list[str] | None
    try:
        installed = list_ollama_models()
    except OllamaUnreachable as exc:
        installed = None
        typer.echo(f"Note: {exc}, so court.yaml uses the default models.")
    text = write_court_yaml(config, installed, force=True)
    typer.echo(f"Wrote {config}:\n\n{text}")
    typer.echo("Next: `court doctor` checks Ollama and the models, then run `court trial`.")


@app.command()
def doctor(
    pull: Annotated[
        bool, typer.Option(help="Run `ollama pull` for the models that are missing.")
    ] = False,
) -> None:
    """Check Ollama and pull the judge and guard models."""
    checks = run_doctor(pull=pull)
    console = Console()
    console.print(doctor_table(checks))
    if not doctor_ok(checks):
        console.print("Some checks failed. Each row's Fix column says what to do.")
        raise typer.Exit(code=1)
    console.print("Ready for `court trial`.")


# court trial


def _trial_settings(path: Path, *, quick: bool, mock: bool) -> CourtConfig:
    preset: PresetName | None = "quick" if quick else None
    if path.exists():
        return _settings(path, preset)
    _missing(path)
    if not mock:
        _fail(
            f"No {path} here. Write one with `court init`, or try an offline run with "
            "`court trial --quick --mock`."
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


async def _calibrate(run_id: str, store: CourtStore, judge: Judge, console: Console) -> None:
    """Check the Queen's LLM layer against the run's exact rulings and save the row the
    Courtroom shows. The run is already recorded, so a failure here only prints a warning."""
    from wonderland_court.adversaries import calibration
    from wonderland_court.adversaries.judge import QueenJudge

    if not isinstance(judge, QueenJudge) or judge.llm is None:
        return  # the fake judge has no LLM layer
    try:
        with console.status("Checking the judge against the exact rulings..."):
            result = await calibration.calibrate_run(run_id, store, judge)
    except Exception as exc:
        console.print(
            f"[yellow]Judge calibration failed: {escape(f'{type(exc).__name__}: {exc}')}[/]"
        )
        return
    if result.agreement_rate is not None:
        console.print(
            "Judge calibration: the LLM judge agreed with the exact rulings on "
            f"{result.agreement_count} of {result.llm_evaluated} sampled turns "
            f"({result.agreement_rate:.0%}), {result.false_positives} false positives, "
            f"{result.false_negatives} false negatives."
        )
    elif result.total_exact_checked == 0:
        console.print("Judge calibration skipped: no turn was ruled by the canary or tool checks.")
    else:
        console.print(
            "[yellow]Judge calibration not saved: the LLM judge gave no readable ruling.[/]"
        )


async def _trial(
    settings: CourtConfig,
    *,
    mock: bool,
    agent: Target | None,
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
            client = RateLimitedLLMClient(cache=SQLiteResponseCache(store))
            set_default_client(client)  # a Python agent may borrow it, as the tea shop's does
            if agent is not None:
                target = agent
            else:
                assert isinstance(settings.target, str)
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
        await _calibrate(result.run_id, store, judge, console)
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

    # An agent is built here, so a bad entrypoint, URL or ${ENV_VAR} is a usage error. A model
    # target waits for the run's rate-limited client.
    agent: Target | None = None
    if mock:
        name, kind = MockTarget.name, MockTarget.kind
    else:
        try:
            if is_agent_target(settings.target):
                agent = build_target(settings.target)
                name, kind = agent.name, agent.kind
            else:
                assert isinstance(settings.target, str)
                name, kind = canonical_spec(settings.target), TargetKind.MODEL
        except ValueError as exc:
            _fail(str(exc), code=2)
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
                agent=agent,
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
        check = "Run `court doctor` to check that Ollama is running and the models are pulled."
        if kind is TargetKind.AGENT:
            check = f"Check that {name} is working. {check}"
        _fail(
            f"The trial stopped: {type(exc).__name__}: {exc}\n"
            f"The run is marked failed in {settings.db_path}. {check}"
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


def _hardened_defense(path: Path) -> str:
    """The one defense stack in a `court advise` patch."""
    if not path.is_file():
        _fail(f"No hardened config at {path}. Run `court advise` first.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _fail(f"can't read {path}: {exc}", code=2)
    defenses = data.get("defenses") if isinstance(data, dict) else None
    if not (isinstance(defenses, list) and len(defenses) == 1 and isinstance(defenses[0], str)):
        _fail(f"{path} should list exactly one defense stack under `defenses:`.", code=2)
    return defenses[0]


async def _retrial(
    remediator: registry.Remediator,
    db_path: Path,
    baseline: RunRecord,
    defense: str,
    console: Console,
) -> RetrialComparison:
    """Replay `baseline` behind `defense` with the target, models and settings it ran with."""
    config = CourtConfig.model_validate(baseline.config)
    async with CourtStore(db_path, jsonl_dir=db_path.parent / "runs") as store:
        target: Target
        attacker: Attacker
        judge: Judge
        if baseline.target == MockTarget.name:
            client = default_client()
            target, attacker, judge = (
                MockTarget(),
                registry.ScriptedAttacker(),
                registry.CanaryJudge(),
            )
        else:
            if not isinstance(config.target, str):
                raise ValueError("retrying an agent target needs agent targets (#19)")
            client = RateLimitedLLMClient(cache=SQLiteResponseCache(store))
            set_default_client(client)
            target = build_target(config.target, client)
            attacker = registry.load_attacker(config, client)
            judge = registry.load_judge(config, client)
        utility = registry.load_utility_evaluator(config, client)
        total = len(await store.get_matches(baseline.run_id))
        with Progress(console=console, transient=True) as progress:
            return await remediator.retrial(
                store,
                baseline.run_id,
                defense=defense,
                target=target,
                attacker=attacker,
                judge=judge,
                utility=utility,
                on_event=_Reporter(progress, total),
            )


def _share(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _print_retrial(console: Console, comparison: RetrialComparison, defense: str) -> None:
    table = Table(
        title=escape(
            f"Retrial {comparison.retrial_run_id} of {comparison.baseline_run_id}, same seeds"
        )
    )
    for column in ("Scenario", "Matches", "Attack success before", "After", "Change"):
        table.add_column(column)
    for scenario, diff in sorted(comparison.per_scenario.items()):
        table.add_row(
            escape(scenario),
            str(diff["paired"]),
            _share(diff["baseline_asr"]),
            _share(diff["retrial_asr"]),
            f"{diff['asr_delta'] * 100:+.0f} pts",
        )
    table.add_row(
        "all",
        str(len(comparison.matched_seeds)),
        _share(comparison.baseline_asr),
        _share(comparison.retrial_asr),
        f"{comparison.asr_delta * 100:+.0f} pts",
        style="bold",
    )
    console.print(table)
    console.print(
        f"Utility (Dodo pass rate): {_share(comparison.baseline_utility)} before, "
        f"{_share(comparison.retrial_utility)} after, with {escape(defense)}."
    )


@app.command()
def retrial(
    config: ConfigOption = DEFAULT_CONFIG,
    run: Annotated[
        str | None,
        typer.Option(help="Baseline run id. Defaults to the latest run that isn't a retrial."),
    ] = None,
    hardened: HardenedOption = None,
    db: DbOption = None,
) -> None:
    """Re-run the same seeds against the hardened config."""
    console = Console()
    remediator = _remediator(_settings(config), "retrial")
    db_path = _db_path(db, config)
    path = _hardened_path(hardened, config)
    defense = _hardened_defense(path)
    baseline = _run_or_fail(db_path, run, retrials=False)
    console.print(
        escape(f"Retrying run {baseline.run_id} on the same seeds with {defense} ({path}).")
    )
    try:
        comparison = asyncio.run(_retrial(remediator, db_path, baseline, defense, console))
    except registry.NotBuiltError as exc:
        _fail(f"court retrial: {exc}. Edit {path} to a stack that runs today.")
    except (LookupError, ValueError) as exc:
        _fail(f"court retrial: {exc}")
    except Exception as exc:
        if baseline.target == MockTarget.name:
            raise  # nothing outside Court runs in a mock retrial, so this is a bug
        _fail(
            f"The retrial stopped: {type(exc).__name__}: {exc}\n"
            f"The retrial run is marked failed in {db_path}. {CHECK_MODELS}"
        )
    _print_retrial(console, comparison, defense)


@app.command(hidden=True)
def schema() -> None:
    """Print the event JSON Schema, for generating the Courtroom's TypeScript types."""
    typer.echo(json.dumps(event_json_schema(), indent=2))
