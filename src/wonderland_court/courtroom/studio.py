"""All-in-one local studio manager for launching trials, advice, and retrials from the UI."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from wonderland_court import registry
from wonderland_court.config import CourtConfig
from wonderland_court.contracts import (
    Attacker,
    Event,
    Judge,
    MatchEnded,
    MatchMode,
    MatchStarted,
    RunStarted,
    ScenarioId,
    Target,
    TargetKind,
)
from wonderland_court.engine.cache import SQLiteResponseCache
from wonderland_court.engine.defenses import parse_defenses
from wonderland_court.engine.init_doctor import OllamaUnreachable, list_ollama_models
from wonderland_court.engine.mock import MockDefenseModel, MockTarget
from wonderland_court.engine.runner import plan_matches
from wonderland_court.engine.store import CourtReader, CourtStore
from wonderland_court.engine.targets import (
    ChatClient,
    build_target,
    canonical_spec,
    is_agent_target,
)
from wonderland_court.engine.tournament import run_tournament
from wonderland_court.llm import RateLimitedLLMClient, default_client, set_default_client

JobKind = Literal["trial", "advise", "retrial"]
JobStatus = Literal["running", "completed", "failed"]

ALL_SCENARIOS: list[ScenarioId] = [
    ScenarioId.REFUND_TOOL,
    ScenarioId.VAULT,
    ScenarioId.SYSTEM_PROMPT,
    ScenarioId.DRINK_ME,
    ScenarioId.MCP_POISON,
]

DEFAULT_DEFENSES: list[str] = [
    "plain",
    "sandwich",
    "spotlighting",
    "spotlighting+output_filter",
]

ALL_MODEL_DEFENSES: list[str] = [
    "plain",
    "sandwich",
    "input_filter",
    "output_filter",
    "spotlighting",
    "spotlighting+output_filter",
    "dual_llm",
    "spotlighting+guard+output_filter",
]


class StartTrialRequest(BaseModel):
    """Payload to launch a local trial directly from the Courtroom UI."""

    target: str = Field(min_length=1)
    scenarios: list[ScenarioId] = Field(
        default_factory=lambda: [ScenarioId.REFUND_TOOL, ScenarioId.VAULT],
        min_length=1,
    )
    defenses: list[str] = Field(
        default_factory=lambda: list(DEFAULT_DEFENSES),
        min_length=1,
    )
    mode: MatchMode = MatchMode.ADAPTIVE
    rounds: int = Field(default=1, ge=1, le=5)
    max_turns: int = Field(default=3, ge=1, le=8)
    attacker_model: str | None = None
    judge_model: str | None = None
    utility: bool = False


class StartRetrialRequest(BaseModel):
    """Payload to launch a seed-locked retrial from the Courtroom UI."""

    defense: str | None = None


@dataclass
class StudioJob:
    """In-memory progress tracker for a background trial or retrial."""

    job_id: str
    kind: JobKind
    status: JobStatus = "running"
    run_id: str | None = None
    progress_done: int = 0
    progress_total: int = 0
    message: str = "Starting…"
    error: str | None = None
    retrial_run_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "run_id": self.run_id,
            "retrial_run_id": self.retrial_run_id,
            "progress_done": self.progress_done,
            "progress_total": self.progress_total,
            "message": self.message,
            "error": self.error,
        }


def _is_embedding_model(name: str) -> bool:
    lower = name.lower()
    return "embed" in lower or "bge-" in lower or "nomic-" in lower


def _discover_ollama() -> tuple[bool, list[str], list[str]]:
    """Return `(available, chat_models, embed_models)` from the local Ollama daemon."""
    try:
        installed = list_ollama_models()
    except OllamaUnreachable:
        return False, [], []
    chat_models = [m for m in installed if not _is_embedding_model(m)]
    embed_models = [m for m in installed if _is_embedding_model(m)]
    return True, chat_models, embed_models


def _pick_support_models(
    target_spec: str,
    *,
    attacker_override: str | None,
    judge_override: str | None,
) -> tuple[str, str, str, str]:
    """Choose attacker, judge, guard, and embed models that actually exist on this machine."""
    ollama_ok, chat_models, embed_models = _discover_ollama()

    preferred_local = chat_models[0] if chat_models else None
    # Prefer smaller fast models (7b/8b/4b) as default helper if available
    for candidate in chat_models:
        lower = candidate.lower()
        if any(tag in lower for tag in (":4b", ":7b", ":8b", "mini", "small")):
            preferred_local = candidate
            break

    is_ollama_target = target_spec.startswith("ollama:")
    target_bare = target_spec.removeprefix("ollama:") if is_ollama_target else target_spec

    fallback_chat = (
        target_bare
        if is_ollama_target
        else (preferred_local if ollama_ok and preferred_local else target_spec)
    )

    attacker_model = attacker_override or fallback_chat
    judge_model = judge_override or fallback_chat
    guard_model = next(
        (m for m in chat_models if "guard" in m.lower()),
        judge_model,
    )
    embed_model = embed_models[0] if embed_models else "nomic-embed-text"
    return attacker_model, judge_model, guard_model, embed_model


def _normalize_target(raw_target: str) -> tuple[bool, str, TargetKind]:
    cleaned = raw_target.strip()
    if cleaned.lower() in ("mock", MockTarget.name.lower()):
        return True, MockTarget.name, TargetKind.MODEL
    if is_agent_target(cleaned):
        return False, cleaned, TargetKind.AGENT
    return False, canonical_spec(cleaned), TargetKind.MODEL


def _filter_runnable_defenses(defenses: list[str], kind: TargetKind) -> list[str]:
    runnable: list[str] = []
    for stack in defenses:
        try:
            parse_defenses(stack, kind)
        except (registry.NotBuiltError, ValueError):
            continue
        runnable.append(stack)
    if not runnable:
        raise ValueError("None of the selected defenses are compatible with this target.")
    return runnable


class LocalStudioManager:
    """Runs trials, Caterpillar advice, and retrials locally from the web UI."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._jobs: dict[str, StudioJob] = {}
        self._active_job_id: str | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def get_active_job(self) -> StudioJob | None:
        if self._active_job_id is None:
            return None
        return self._jobs.get(self._active_job_id)

    def get_job(self, job_id: str) -> StudioJob | None:
        return self._jobs.get(job_id)

    def has_running_job(self) -> bool:
        active = self.get_active_job()
        return active is not None and active.status == "running"

    def get_options(self) -> dict[str, Any]:
        ollama_ok, chat_models, embed_models = _discover_ollama()
        active = self.get_active_job()
        return {
            "ollama_available": ollama_ok,
            "ollama_models": chat_models,
            "embed_models": embed_models,
            "scenarios": [s.value for s in ALL_SCENARIOS],
            "defenses": list(ALL_MODEL_DEFENSES),
            "default_defenses": list(DEFAULT_DEFENSES),
            "active_job": active.to_dict() if active is not None else None,
        }

    async def start_trial(self, req: StartTrialRequest) -> StudioJob:
        if self.has_running_job():
            raise RuntimeError("A trial or retrial is already running. Wait for it to finish.")

        is_mock, target_spec, target_kind = _normalize_target(req.target)
        defenses = _filter_runnable_defenses(req.defenses, target_kind)

        if is_mock:
            attacker_model = "mock"
            judge_model = "mock"
            guard_model = "mock"
            embed_model = "mock"
        else:
            attacker_model, judge_model, guard_model, embed_model = _pick_support_models(
                target_spec,
                attacker_override=req.attacker_model,
                judge_override=req.judge_model,
            )

        settings = CourtConfig(
            target=target_spec,
            preset="quick",
            defenses=defenses,
            scenarios=req.scenarios,
            mode=req.mode,
            rounds=req.rounds,
            max_turns=req.max_turns,
            attacker_model=attacker_model,
            judge_model=judge_model,
            guard_model=guard_model,
            embed_model=embed_model,
            db_path=self.db_path,
        )

        planned = plan_matches(
            settings,
            target=target_spec,
            target_kind=target_kind,
            attacker="",
            defenses=defenses,
        )

        job = StudioJob(
            job_id=f"job-{uuid.uuid4().hex[:8]}",
            kind="trial",
            status="running",
            progress_done=0,
            progress_total=len(planned),
            message=f"Starting {len(planned)} trials against {target_spec}…",
        )
        self._jobs[job.job_id] = job
        self._active_job_id = job.job_id

        started_event = asyncio.Event()

        async def _runner() -> None:
            jsonl_dir = self.db_path.parent / "runs"
            try:
                async with CourtStore(self.db_path, jsonl_dir=jsonl_dir) as store:
                    target: Target
                    attacker: Attacker
                    judge: Judge
                    defense_llm: ChatClient
                    dodo: registry.UtilityEvaluator | None = None

                    if is_mock:
                        target = MockTarget()
                        attacker = registry.ScriptedAttacker()
                        judge = registry.CanaryJudge()
                        defense_llm = MockDefenseModel()
                    else:
                        client = RateLimitedLLMClient(cache=SQLiteResponseCache(store))
                        set_default_client(client)
                        target = build_target(target_spec, client)
                        defense_llm = client
                        attacker = registry.load_attacker(settings, client)
                        judge = registry.load_judge(settings, client)
                        if req.utility:
                            dodo = registry.load_utility_evaluator(settings, client)

                    def _on_event(ev: Event) -> None:
                        if isinstance(ev, RunStarted):
                            job.run_id = ev.run_id
                            started_event.set()
                        elif isinstance(ev, MatchStarted):
                            job.message = f"Running {ev.match.scenario.value} ({ev.match.defense})…"
                        elif isinstance(ev, MatchEnded):
                            job.progress_done += 1
                            job.message = (
                                f"Completed {job.progress_done} of {job.progress_total} trials…"
                            )

                    result = await run_tournament(
                        settings,
                        target=target,
                        attacker=attacker,
                        judge=judge,
                        store=store,
                        defenses=defenses,
                        utility=dodo,
                        on_event=_on_event,
                        defense_llm=defense_llm,
                    )
                    job.run_id = result.run_id
                    started_event.set()

                    # Run lightweight judge calibration if LLM judge was used
                    from wonderland_court.adversaries import calibration
                    from wonderland_court.adversaries.judge import QueenJudge

                    if isinstance(judge, QueenJudge) and judge.llm is not None:
                        try:
                            job.message = "Calibrating Queen of Hearts judge…"
                            await calibration.calibrate_run(result.run_id, store, judge)
                        except Exception:
                            pass

                job.status = "completed"
                job.progress_done = job.progress_total
                job.message = f"Finished {len(result.matches)} trials ({result.leaks} breached)."
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.message = f"Trial failed: {exc}"
                started_event.set()

        task = asyncio.create_task(_runner())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(started_event.wait(), timeout=5.0)

        if job.status == "failed" and job.run_id is None:
            raise RuntimeError(job.error or "Failed to start trial.")

        return job

    async def run_advise(self, run_id: str) -> dict[str, Any]:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"No database found at {self.db_path}.")

        async with CourtReader(self.db_path) as reader:
            record = await reader.get_run(run_id)
        if record is None:
            raise LookupError(f"Run '{run_id}' not found.")

        config = CourtConfig.model_validate(record.config)
        is_mock = record.target == MockTarget.name
        if not is_mock and isinstance(config.target, str):
            attacker_m, judge_m, guard_m, embed_m = _pick_support_models(
                config.target,
                attacker_override=None,
                judge_override=None,
            )
            config = config.model_copy(
                update={
                    "attacker_model": attacker_m,
                    "judge_model": judge_m,
                    "guard_model": guard_m,
                    "embed_model": embed_m,
                }
            )

        client = default_client() if is_mock else RateLimitedLLMClient()
        remediator = registry.load_remediator(config, client)
        if isinstance(remediator, registry.NotBuilt):
            raise RuntimeError("Caterpillar remediator is not available.")

        hardened_path = self.db_path.parent / f"{run_id}.hardened.yaml"
        advice = await remediator.advise(self.db_path, run_id, hardened_path=hardened_path)
        return {
            "run_id": advice.run_id,
            "target_kind": advice.target_kind.value,
            "clusters": list(advice.clusters),
            "recommended_defense": advice.recommended_defense,
            "config_patch_yaml": advice.config_patch_yaml,
            "rationale": advice.rationale,
        }

    async def start_retrial(
        self,
        run_id: str,
        *,
        defense: str | None = None,
    ) -> StudioJob:
        if self.has_running_job():
            raise RuntimeError("A trial or retrial is already running. Wait for it to finish.")
        if not self.db_path.is_file():
            raise FileNotFoundError(f"No database found at {self.db_path}.")

        async with CourtReader(self.db_path) as reader:
            baseline = await reader.get_run(run_id)
            if baseline is None:
                raise LookupError(f"Run '{run_id}' not found.")
            saved_advice = await reader.get_advice(run_id)
            total_matches = len(await reader.get_matches(run_id))

        chosen_defense = defense
        if not chosen_defense:
            if saved_advice is not None:
                chosen_defense = saved_advice.recommended_defense
            else:
                chosen_defense = "spotlighting+output_filter"

        config = CourtConfig.model_validate(baseline.config)
        is_mock = baseline.target == MockTarget.name
        if not is_mock and isinstance(config.target, str):
            attacker_m, judge_m, guard_m, embed_m = _pick_support_models(
                config.target,
                attacker_override=None,
                judge_override=None,
            )
            config = config.model_copy(
                update={
                    "attacker_model": attacker_m,
                    "judge_model": judge_m,
                    "guard_model": guard_m,
                    "embed_model": embed_m,
                }
            )

        job = StudioJob(
            job_id=f"job-{uuid.uuid4().hex[:8]}",
            kind="retrial",
            status="running",
            run_id=run_id,
            progress_done=0,
            progress_total=total_matches,
            message=f"Retrying {total_matches} matched seeds with {chosen_defense}…",
        )
        self._jobs[job.job_id] = job
        self._active_job_id = job.job_id

        async def _runner() -> None:
            try:
                jsonl_dir = self.db_path.parent / "runs"
                async with CourtStore(self.db_path, jsonl_dir=jsonl_dir) as store:
                    target: Target
                    attacker: Attacker
                    judge: Judge
                    defense_llm: ChatClient
                    if is_mock:
                        client = default_client()
                        target = MockTarget()
                        attacker = registry.ScriptedAttacker()
                        judge = registry.CanaryJudge()
                        defense_llm = MockDefenseModel()
                    else:
                        if not isinstance(config.target, str):
                            raise ValueError(
                                "Retrying non-string agent targets is not supported yet."
                            )
                        client = RateLimitedLLMClient(cache=SQLiteResponseCache(store))
                        set_default_client(client)
                        target = build_target(config.target, client)
                        attacker = registry.load_attacker(config, client)
                        judge = registry.load_judge(config, client)
                        defense_llm = client

                    remediator = registry.load_remediator(config, client)
                    if isinstance(remediator, registry.NotBuilt):
                        raise RuntimeError("Caterpillar remediator is not available.")

                    def _on_event(ev: Event) -> None:
                        if isinstance(ev, MatchEnded):
                            job.progress_done += 1
                            job.message = (
                                f"Retried {job.progress_done} of {job.progress_total} matches…"
                            )

                    utility = registry.load_utility_evaluator(config, client)

                    comparison = await remediator.retrial(
                        store,
                        run_id,
                        defense=chosen_defense,
                        target=target,
                        attacker=attacker,
                        judge=judge,
                        utility=utility,
                        on_event=_on_event,
                        defense_llm=defense_llm,
                    )
                    job.retrial_run_id = comparison.retrial_run_id
                    job.status = "completed"
                    job.progress_done = job.progress_total
                    job.message = (
                        f"Retrial complete: breach rate {comparison.baseline_asr:.0%} → "
                        f"{comparison.retrial_asr:.0%}."
                    )
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.message = f"Retrial failed: {exc}"

        task = asyncio.create_task(_runner())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job
