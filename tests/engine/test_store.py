"""CourtStore, CourtReader and the response cache, against real SQLite files in a temp dir.

Nothing here calls a model. The recorded fake run supplies the events and match results.
"""

import asyncio
import contextlib
import itertools
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from wonderland_court.contracts import (
    Event,
    MatchEnded,
    MatchMode,
    MatchSpec,
    MatchStarted,
    ScenarioId,
    StandingsUpdated,
    TargetKind,
    TargetReply,
    ToolCall,
    dump_event,
    parse_event,
)
from wonderland_court.engine.cache import SQLiteResponseCache
from wonderland_court.engine.store import (
    CourtReader,
    CourtStore,
    JudgeCalibration,
    MatchRecord,
    RemediationAdvice,
    RetrialComparison,
    RunRecord,
    UtilityResult,
)
from wonderland_court.llm import ResponseCache

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "fake_run.jsonl"
LINES = FIXTURE.read_text(encoding="utf-8").splitlines()
EVENTS = [parse_event(line) for line in LINES]
RUN_ID = EVENTS[0].run_id
SPECS = {e.match.match_id: e.match for e in EVENTS if isinstance(e, MatchStarted)}
RESULTS = [e for e in EVENTS if isinstance(e, MatchEnded)]
TABLES = {
    "runs",
    "events",
    "matches",
    "standings",
    "utility_results",
    "judge_calibration",
    "remediation_advice",
    "retrial_comparisons",
    "llm_cache",
}


def restamp(event: Event, run_id: str, seq: int) -> Event:
    return event.model_copy(update={"run_id": run_id, "seq": seq})


def read_only(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)


async def pragma(db: aiosqlite.Connection, name: str) -> object:
    [(value,)] = await db.execute_fetchall(f"PRAGMA {name}")
    return value


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[CourtStore]:
    async with CourtStore(tmp_path / "court.db") as store:
        yield store


# The event log


@pytest.mark.asyncio
async def test_fake_run_round_trips_through_the_store_and_the_jsonl_sink(tmp_path: Path) -> None:
    db_path, sink_dir = tmp_path / "court.db", tmp_path / "runs"
    async with CourtStore(db_path, jsonl_dir=sink_dir) as store:
        for event in EVENTS:
            await store.append_event(event)
        assert [dump_event(e) for e in await store.get_events_after(RUN_ID)] == LINES

    assert (sink_dir / f"{RUN_ID}.jsonl").read_bytes() == FIXTURE.read_bytes()
    with contextlib.closing(read_only(db_path)) as db:
        stored = [line for (line,) in db.execute("SELECT event_json FROM events ORDER BY seq")]
    assert stored == LINES

    async with CourtReader(db_path) as reader:
        assert [dump_event(e) for e in await reader.get_events_after(RUN_ID)] == LINES
        tail = await reader.get_events_after(RUN_ID, after_seq=70)
        assert [e.seq for e in tail] == list(range(71, len(LINES)))
        assert await reader.get_events_after("another-run") == []


@pytest.mark.asyncio
async def test_store_runs_in_wal_mode_on_a_file(tmp_path: Path) -> None:
    db_path = tmp_path / "court.db"
    async with CourtStore(db_path) as store:
        assert (tmp_path / "court.db-wal").exists()
        assert store._write_db is not None
        assert await pragma(store._write_db, "journal_mode") == "wal"
        assert await pragma(store._write_db, "synchronous") == 1  # NORMAL
        assert await pragma(store._write_db, "busy_timeout") == 5000
        assert await pragma(store._write_db, "foreign_keys") == 1
        with contextlib.closing(read_only(db_path)) as db:
            assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
            names = {
                name
                for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
    assert names == TABLES


@pytest.mark.asyncio
async def test_twenty_writers_and_three_read_only_tailers(tmp_path: Path) -> None:
    writers, per_writer, tailers = 20, 25, 3
    total = writers * per_writer
    db_path = tmp_path / "court.db"
    seqs = itertools.count()

    async def write(store: CourtStore, writer: int) -> None:
        for i in range(per_writer):
            # Taking the seq and queueing the write happen with no await between them, the way
            # the scheduler numbers events, so the queue holds them in seq order.
            seq = next(seqs)
            await store.append_event(restamp(EVENTS[seq % len(EVENTS)], "stress", seq))
            await store.cache_put(f"{writer}:{i}", TargetReply(content=str(seq)))

    async def tail() -> list[int]:
        seen: list[int] = []
        async with CourtReader(db_path) as reader:
            while len(seen) < total:
                for event in await reader.get_events_after("stress", seen[-1] if seen else -1):
                    seen.append(event.seq)
                await asyncio.sleep(0.001)
        return seen

    async with CourtStore(db_path, jsonl_dir=tmp_path) as store:
        async with asyncio.timeout(60):
            tailing = [asyncio.create_task(tail()) for _ in range(tailers)]
            await asyncio.gather(*(write(store, n) for n in range(writers)))
            seen = await asyncio.gather(*tailing)

        assert seen == [list(range(total))] * tailers
        assert [e.seq for e in await store.get_events_after("stress")] == list(range(total))
        for n in range(writers):
            assert await store.cache_get(f"{n}:{per_writer - 1}") is not None

    sink = (tmp_path / "stress.jsonl").read_text(encoding="utf-8").splitlines()
    assert [parse_event(line).seq for line in sink] == list(range(total))


# Every table


@pytest.mark.asyncio
async def test_runs(store: CourtStore) -> None:
    first = RunRecord(
        run_id="run-1",
        mode=MatchMode.ADAPTIVE,
        target="ollama:llama3.1",
        target_kind=TargetKind.MODEL,
        config={"rounds": 1, "defenses": ["plain", "sandwich"]},
        created_at=datetime(2026, 11, 21, 10, tzinfo=UTC),
    )
    retrial = replace(
        first,
        run_id="run-2",
        parent_run_id="run-1",
        created_at=datetime(2026, 11, 21, 11, tzinfo=UTC),
    )
    await store.create_run(first)
    await store.create_run(retrial)

    assert await store.get_run("run-1") == first
    assert await store.list_runs() == [retrial, first]
    assert await store.get_run("missing") is None

    await store.set_run_status("run-1", "finished")
    assert await store.get_run("run-1") == replace(first, status="finished")
    with pytest.raises(KeyError):
        await store.set_run_status("missing", "finished")


def expected_match(spec: MatchSpec, result: MatchEnded) -> MatchRecord:
    return MatchRecord(
        match_id=spec.match_id,
        run_id=result.run_id,
        round=spec.round,
        target=spec.target,
        target_kind=spec.target_kind,
        defense=spec.defense,
        scenario=spec.scenario,
        mode=spec.mode,
        family=spec.family,
        seed=spec.seed,
        broken=result.broken,
        turns=result.turns,
        broken_on_turn=result.broken_on_turn,
        breaking_family=result.breaking_family,
    )


@pytest.mark.asyncio
async def test_match_results(store: CourtStore) -> None:
    for result in reversed(RESULTS):
        await store.save_match_result(SPECS[result.match_id], result)

    expected = sorted(
        (expected_match(SPECS[r.match_id], r) for r in RESULTS), key=lambda m: m.match_id
    )
    assert await store.get_matches(RUN_ID) == expected
    assert any(m.broken for m in expected) and not all(m.broken for m in expected)
    assert await store.get_matches("another-run") == []

    with pytest.raises(ValueError, match="m01"):
        await store.save_match_result(SPECS["m01"], RESULTS[1])


@pytest.mark.asyncio
async def test_latest_standings_come_from_the_highest_round(store: CourtStore) -> None:
    final = next(e for e in EVENTS if isinstance(e, StandingsUpdated))
    first_round = [s.model_copy(update={"elo": 1500.0}) for s in final.standings]
    await store.upsert_standings(RUN_ID, 1, first_round)
    await store.upsert_standings(RUN_ID, 2, list(reversed(final.standings)))
    assert await store.get_latest_standings(RUN_ID) == final.standings

    leader = final.standings[0].model_copy(update={"matches": 99, "utility": 0.75})
    await store.upsert_standings(RUN_ID, 2, [leader])
    assert await store.get_latest_standings(RUN_ID) == [leader, *final.standings[1:]]
    assert await store.get_latest_standings("another-run") == []


@pytest.mark.asyncio
async def test_utility_results(store: CourtStore) -> None:
    vault = UtilityResult(
        run_id="run-1",
        defense="plain",
        scenario=ScenarioId.VAULT,
        pass_rate=0.9,
        false_refusal_rate=0.05,
        details={"tasks": 20, "refused": ["t3"]},
    )
    refund = replace(vault, scenario=ScenarioId.REFUND_TOOL, pass_rate=0.8)
    await store.save_utility_result(vault)
    await store.save_utility_result(refund)
    await store.save_utility_result(replace(vault, pass_rate=0.95))
    assert await store.get_utility_results("run-1") == [refund, replace(vault, pass_rate=0.95)]
    assert await store.get_utility_results("another-run") == []


@pytest.mark.asyncio
async def test_judge_calibration(store: CourtStore) -> None:
    calibration = JudgeCalibration(
        run_id="run-1",
        total_exact_checked=40,
        llm_evaluated=38,
        agreement_count=36,
        agreement_rate=36 / 38,
        false_positives=1,
        false_negatives=1,
    )
    assert await store.get_calibration("run-1") is None
    await store.save_judge_calibration(calibration)
    assert await store.get_calibration("run-1") == calibration


@pytest.mark.asyncio
async def test_remediation_advice(store: CourtStore) -> None:
    advice = RemediationAdvice(
        run_id="run-1",
        target_kind=TargetKind.MODEL,
        clusters=[{"family": "indirect_injection", "matches": ["m01"], "count": 1}],
        recommended_defense="spotlighting+guard",
        config_patch_yaml="defenses:\n  - spotlighting+guard\n",
        rationale="Every leak came through a poisoned email.",
    )
    assert await store.get_advice("run-1") is None
    await store.save_remediation_advice(advice)
    assert await store.get_advice("run-1") == advice


@pytest.mark.asyncio
async def test_retrial_comparison(store: CourtStore) -> None:
    comparison = RetrialComparison(
        retrial_run_id="run-2",
        baseline_run_id="run-1",
        matched_seeds=[2751, 9120],
        baseline_asr=0.5,
        retrial_asr=0.0,
        asr_delta=-0.5,
        baseline_utility=0.9,
        retrial_utility=None,
        per_scenario={"vault": {"baseline": 0.5, "retrial": 0.0}},
    )
    assert await store.get_retrial_comparison("run-2") is None
    await store.save_retrial_comparison(comparison)
    assert await store.get_retrial_comparison("run-2") == comparison


@pytest.mark.asyncio
async def test_response_cache_stores_replies_by_key(store: CourtStore) -> None:
    cache: ResponseCache = SQLiteResponseCache(store)
    reply = TargetReply(
        content="Done.",
        tool_calls=[ToolCall(id="call-1", name="issue_refund", arguments={"amount": 400})],
        latency_ms=1200,
    )
    assert await cache.get("key-a") is None
    await cache.put("key-a", reply)
    await cache.put("key-b", TargetReply(content="Other"))
    assert await cache.get("key-a") == reply

    newer = reply.model_copy(update={"content": "Refused."})
    await cache.put("key-a", newer)
    assert await cache.get("key-a") == newer
    assert await cache.get("key-b") == TargetReply(content="Other")


@pytest.mark.asyncio
async def test_response_cache_survives_a_restart(tmp_path: Path) -> None:
    reply = TargetReply(content="cached")
    async with CourtStore(tmp_path / "court.db") as store:
        await SQLiteResponseCache(store).put("key", reply)
    async with CourtStore(tmp_path / "court.db") as store:
        assert await SQLiteResponseCache(store).get("key") == reply


# Failure handling and shutdown


@pytest.mark.asyncio
async def test_failed_writes_reach_their_callers_and_the_writer_keeps_going(tmp_path: Path) -> None:
    sink_dir = tmp_path / "runs"
    async with CourtStore(tmp_path / "court.db", jsonl_dir=sink_dir) as store:
        for event in EVENTS[:10]:
            await store.append_event(event)

        duplicates = [store.append_event(e) for e in EVENTS[:10]]
        fresh = [store.append_event(e) for e in EVENTS[10:20]]
        outcomes = await asyncio.gather(
            *itertools.chain.from_iterable(zip(duplicates, fresh, strict=True)),
            return_exceptions=True,
        )
        assert all(isinstance(o, sqlite3.IntegrityError) for o in outcomes[::2])
        assert outcomes[1::2] == [None] * 10

        result = RESULTS[0]
        await store.save_match_result(SPECS[result.match_id], result)
        with pytest.raises(sqlite3.IntegrityError):  # match ids are unique across runs
            await store.save_match_result(SPECS[result.match_id], result)

        assert [e.seq for e in await store.get_events_after(RUN_ID)] == list(range(20))

    # A rejected event never reaches the JSONL file.
    assert (sink_dir / f"{RUN_ID}.jsonl").read_text(encoding="utf-8").splitlines() == LINES[:20]


@pytest.mark.asyncio
async def test_unsafe_run_id_is_rejected_before_anything_is_written(tmp_path: Path) -> None:
    async with CourtStore(tmp_path / "court.db", jsonl_dir=tmp_path / "runs") as store:
        with pytest.raises(ValueError, match="file name"):
            await store.append_event(restamp(EVENTS[0], "../escape", 0))
        assert await store.get_events_after("../escape") == []
    assert not (tmp_path / "escape.jsonl").exists()


@pytest.mark.asyncio
async def test_close_drains_queued_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "court.db"
    store = CourtStore(db_path)
    await store.start()
    pending = [asyncio.create_task(store.append_event(e)) for e in EVENTS]
    await asyncio.sleep(0)  # every task queues its write
    assert not any(task.done() for task in pending)

    await store.close()
    assert all(task.done() and task.exception() is None for task in pending)
    await store.close()  # a second close is a no-op

    with pytest.raises(RuntimeError, match="closed"):
        await store.append_event(EVENTS[0])
    async with CourtReader(db_path) as reader:
        assert [dump_event(e) for e in await reader.get_events_after(RUN_ID)] == LINES


@pytest.mark.asyncio
async def test_reader_never_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "court.db"
    with pytest.raises(FileNotFoundError):
        await CourtReader(db_path).start()
    assert not db_path.exists()

    async with CourtStore(db_path), CourtReader(db_path) as reader:
        assert reader._read_db is not None
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            await reader._read_db.execute("INSERT INTO llm_cache VALUES ('k', '{}', 'now')")


@pytest.mark.asyncio
async def test_writes_need_a_started_store(tmp_path: Path) -> None:
    store = CourtStore(tmp_path / "court.db")
    with pytest.raises(RuntimeError, match="not started"):
        await store.cache_put("key", TargetReply(content="x"))
    with pytest.raises(RuntimeError, match="not started"):
        await store.cache_get("key")
