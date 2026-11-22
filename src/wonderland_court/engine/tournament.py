"""The White Rabbit's tournament: rounds of matches, a live leaderboard, then the Dodo.

`run_tournament` plays the schedule from `runner.plan_matches` (rounds x scenarios x defenses,
and x families in fixed mode) one round at a time. Every defense in a round faces the same
seed. The seeds come from `config.seed`, which the run's `config_json` keeps, and each match's
seed is in the `matches` table, so `court retrial` can replay them exactly. After each round
the tournament scores every match finished so far (`scoring.compute_standings`), saves the
board with `upsert_standings` and emits `StandingsUpdated`, so the Courtroom leaderboard moves
while the trial runs.

After the last round the Dodo (`registry.load_utility_evaluator`) scores each defense on benign
tasks in each scenario. Its pass rates go to `utility_results`, break Elo ties between two
defenses that both held, and fill `Standing.utility` in one more `StandingsUpdated` for the
last round. With no evaluator, or a scenario it has no tasks for, utility stays blank.

`config.match_timeout_s` bounds each match and each Dodo check. Only model calls are cut short,
never an event write, so the event log stays whole. A match that runs over ends with
`match_ended` after the turns it finished and is left out of the `matches` table and the
standings, since running out of time says nothing about the defense.

With `config.shard` set to `k/N`, only that part of the schedule and of the Dodo checks runs
here. `court merge` joins the parts (see `sharding`).
"""

import asyncio
import contextlib
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, TypeVar

from wonderland_court.config import CourtConfig
from wonderland_court.contracts import (
    Attack,
    AttackContext,
    Attacker,
    Event,
    Judge,
    MatchEnded,
    MatchSpec,
    Message,
    MutatorId,
    RunEnded,
    RunStarted,
    ScenarioId,
    Stakes,
    Standing,
    Target,
    TargetReply,
    TargetRequest,
    TechniqueFamily,
    ToolSpec,
    Verdict,
    VerdictRuled,
)
from wonderland_court.registry import UtilityEvaluator

from .defenses import DefenseModels, DefensePolicy, compose_defenses
from .runner import EventLog, MatchResult, TrialResult, new_run_id, plan_matches, run_match
from .scenarios import build_scenario
from .scoring import Utility, compute_standings
from .sharding import Shard, publish_standings
from .store import CourtStore, MatchRecord, RunRecord, UtilityResult
from .targets import ChatClient

logger = logging.getLogger(__name__)
T = TypeVar("T")


def _now() -> datetime:
    return datetime.now(UTC)


# Time limits


class MatchTimeout(Exception):
    """A match or a Dodo check ran past `match_timeout_s`."""


class Deadline:
    """One match's time limit, shared by every model call the match makes."""

    def __init__(self, seconds: float | None) -> None:
        self.seconds = seconds
        self._at = None if seconds is None else asyncio.get_running_loop().time() + seconds

    async def __call__(self, call: Awaitable[T]) -> T:
        if self._at is None:
            return await call
        timeout = asyncio.timeout_at(self._at)
        try:
            async with timeout:
                return await call
        except TimeoutError:
            if timeout.expired():
                raise MatchTimeout(f"ran past {self.seconds:g}s") from None
            raise


class _TimedTarget:
    def __init__(self, target: Target, deadline: Deadline) -> None:
        self.name = target.name
        self.kind = target.kind
        self._target = target
        self._deadline = deadline

    async def respond(self, request: TargetRequest) -> TargetReply:
        return await self._deadline(self._target.respond(request))


class _TimedAttacker:
    def __init__(self, attacker: Attacker, deadline: Deadline) -> None:
        self.name = attacker.name
        self._attacker = attacker
        self._deadline = deadline

    async def next_attack(self, context: AttackContext) -> Attack:
        return await self._deadline(self._attacker.next_attack(context))


class _TimedJudge:
    def __init__(self, judge: Judge, deadline: Deadline) -> None:
        self._judge = judge
        self._deadline = deadline

    async def rule(self, stakes: Stakes, attack: Attack, reply: TargetReply) -> Verdict:
        return await self._deadline(self._judge.rule(stakes, attack, reply))


class _TimedChat:
    def __init__(self, client: ChatClient, deadline: Deadline) -> None:
        self._client = client
        self._deadline = deadline

    async def chat(
        self,
        model_spec: str,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        tools: list[ToolSpec] | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> TargetReply:
        call = self._client.chat(
            model_spec,
            messages,
            system_prompt=system_prompt,
            tools=tools,
            json_schema=json_schema,
            temperature=temperature,
            seed=seed,
        )
        return await self._deadline(call)


@dataclass(frozen=True)
class _Players:
    target: Target
    attacker: Attacker
    judge: Judge
    models: DefenseModels


def _on_time(players: _Players, deadline: Deadline) -> _Players:
    """The same players, with every model call they make bound by `deadline`."""
    if deadline.seconds is None:
        return players
    return _Players(
        _TimedTarget(players.target, deadline),
        _TimedAttacker(players.attacker, deadline),
        _TimedJudge(players.judge, deadline),
        replace(players.models, llm=_TimedChat(players.models.client(), deadline)),
    )


# The tournament


@dataclass(frozen=True)
class TournamentResult(TrialResult):
    """A finished tournament. `matches` holds the matches that finished in time, in schedule
    order. `standings` is the final leaderboard, with utility when the Dodo scored any."""

    standings: list[Standing] = field(default_factory=list)
    utility: list[UtilityResult] = field(default_factory=list)
    timed_out: list[str] = field(default_factory=list)
    """Ids of the matches that ran past `match_timeout_s`."""
    shard: str | None = None


async def run_tournament(
    config: CourtConfig,
    *,
    target: Target,
    attacker: Attacker,
    judge: Judge,
    store: CourtStore,
    defenses: Sequence[str] | None = None,
    families: Sequence[TechniqueFamily] = (),
    mutators: Sequence[MutatorId] = (),
    specs: Sequence[MatchSpec] | None = None,
    utility: UtilityEvaluator | None = None,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    concurrency: int = 2,
    on_event: Callable[[Event], None] | None = None,
    clock: Callable[[], datetime] = _now,
    defense_llm: ChatClient | None = None,
) -> TournamentResult:
    """Play the tournament round by round, `concurrency` matches at a time, and record it.

    The schedule is `plan_matches` over `defenses` (the config's by default), or `specs` as
    given, as a retrial does with its baseline's matches. `utility` is the Dodo; None skips
    the utility checks. Model-backed defenses call through `defense_llm`, or the shared
    default client when it is None. The shared LLM client enforces the real rate limits.

    The run ends `finished`, or `failed` if anything but a timeout raised, and the first match
    error is re-raised as is. A Dodo check that fails is logged and left blank.
    """
    if specs is None:
        defenses = list(config.defenses if defenses is None else defenses)
        schedule = plan_matches(
            config,
            target=target.name,
            target_kind=target.kind,
            attacker=attacker.name,
            defenses=defenses,
            families=families,
            mutators=mutators,
        )
    else:
        schedule = list(specs)
        defenses = list(
            dict.fromkeys(spec.defense for spec in schedule) if defenses is None else defenses
        )
    shard = Shard.parse(config.shard) if config.shard else None
    mine = shard.select(schedule) if shard else schedule
    rounds = sorted({spec.round for spec in schedule})
    run_id = run_id or new_run_id()

    finished_turns: Counter[str] = Counter()

    async def record(event: Event) -> None:
        await store.append_event(event)
        if isinstance(event, VerdictRuled):
            finished_turns[event.match_id] += 1

    events = EventLog(run_id, record, clock, listener=on_event)
    await store.create_run(
        RunRecord(
            run_id=run_id,
            mode=config.mode,
            target=target.name,
            target_kind=target.kind,
            config=config.model_dump(mode="json"),
            parent_run_id=parent_run_id,
        )
    )
    gate = asyncio.Semaphore(concurrency)
    players = _Players(
        target,
        attacker,
        judge,
        DefenseModels(
            guard=config.guard_model, quarantine=config.quarantine_model, llm=defense_llm
        ),
    )
    timed_out: list[str] = []

    async def play(spec: MatchSpec) -> MatchResult | None:
        async with gate:
            deadline = Deadline(config.match_timeout_s)
            on_time = _on_time(players, deadline)
            try:
                result = await run_match(
                    spec,
                    on_time.target,
                    on_time.attacker,
                    on_time.judge,
                    events,
                    models=on_time.models,
                )
            except MatchTimeout:
                logger.warning(
                    "match %s ran past %gs and is left out of the standings",
                    spec.match_id,
                    deadline.seconds,
                )
                timed_out.append(spec.match_id)
                turns = finished_turns[spec.match_id]
                await events.emit(MatchEnded, match_id=spec.match_id, broken=False, turns=turns)
                return None
            await store.save_match_result(spec, result.ended)
            return result

    played: list[MatchResult] = []
    standings = compute_standings([], defenses=defenses)
    scored: list[UtilityResult] = []
    try:
        await events.emit(
            RunStarted,
            targets=[target.name],
            defenses=defenses,
            scenarios=list(dict.fromkeys(spec.scenario for spec in schedule))
            or list(config.scenarios),
            mode=config.mode,
            rounds=max(rounds, default=config.rounds),
        )
        for round in rounds:
            batch = await _all(play(spec) for spec in mine if spec.round == round)
            played += [result for result in batch if result is not None]
            standings = compute_standings(_records(played), defenses=defenses)
            await publish_standings(store, events, round, standings)

        if utility is not None and rounds:
            jobs = list(dict.fromkeys((spec.defense, spec.scenario) for spec in schedule))
            scored = await _score_utility(
                utility,
                shard.select(jobs) if shard else jobs,
                run_id=run_id,
                config=config,
                players=players,
                store=store,
                gate=gate,
            )
            if scored:
                table = utility_table(scored)
                standings = compute_standings(_records(played), defenses=defenses, utility=table)
                await publish_standings(store, events, rounds[-1], standings)

        await events.emit(
            RunEnded, matches=len(played), leaks=sum(result.ended.broken for result in played)
        )
    except BaseException:
        with contextlib.suppress(Exception):
            await store.set_run_status(run_id, "failed")
        raise
    await store.set_run_status(run_id, "finished")

    position = {spec.match_id: index for index, spec in enumerate(mine)}
    return TournamentResult(
        run_id,
        played,
        standings=standings,
        utility=scored,
        timed_out=sorted(timed_out, key=position.__getitem__),
        shard=config.shard,
    )


def utility_table(results: Iterable[UtilityResult]) -> Utility:
    """The Dodo's pass rates keyed the way `scoring` reads them."""
    return {(result.defense, result.scenario): result.pass_rate for result in results}


async def _score_utility(
    evaluator: UtilityEvaluator,
    jobs: Sequence[tuple[str, ScenarioId]],
    *,
    run_id: str,
    config: CourtConfig,
    players: _Players,
    store: CourtStore,
    gate: asyncio.Semaphore,
) -> list[UtilityResult]:
    """The Dodo's pass rate for each `(defense, scenario)`, saved to `utility_results`."""
    name = str(getattr(evaluator, "name", type(evaluator).__name__))

    async def score(defense: str, scenario: ScenarioId) -> UtilityResult | None:
        async with gate:
            deadline = Deadline(config.match_timeout_s)
            rules = tuple(build_scenario(scenario, config.seed).stakes.tool_rules)
            defended = compose_defenses(
                defense, players.target, DefensePolicy(tool_rules=rules, models=players.models)
            )
            try:
                value = await deadline(evaluator.evaluate(defended, scenario))
            except MatchTimeout as exc:
                logger.warning("%s on %s in %s %s", name, defense, scenario.value, exc)
                return None
            except Exception:
                logger.warning(
                    "%s couldn't score %s in %s", name, defense, scenario.value, exc_info=True
                )
                return None
        if value is None:
            return None
        result = UtilityResult(
            run_id=run_id,
            defense=defense,
            scenario=scenario,
            pass_rate=value,
            false_refusal_rate=None,
            details={"evaluator": name},
        )
        await store.save_utility_result(result)
        return result

    results = await _all(score(defense, scenario) for defense, scenario in jobs)
    return [result for result in results if result is not None]


def _records(played: Iterable[MatchResult]) -> list[MatchRecord]:
    return [MatchRecord.from_result(result.spec, result.ended) for result in played]


async def _all(calls: Iterable[Coroutine[Any, Any, T]]) -> list[T]:
    """Run the calls at once and return their results in order. The first error cancels the
    rest and is raised as is."""
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(call) for call in calls]
    except ExceptionGroup as errors:
        raise errors.exceptions[0] from errors
    return [task.result() for task in tasks]
