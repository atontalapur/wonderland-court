"""The Adversaries harness: ground-truth corpora, fake clients and factories. Offline only."""

from __future__ import annotations

import asyncio
import json
import math
import re
import socket
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from wonderland_court.adversaries.ports import ChatClient, EmbeddingClient
from wonderland_court.adversaries.refusals import is_refusal
from wonderland_court.contracts.models import Message, ScenarioId, TargetReply

from .fakes import CANARY, FakeEmbeddingClient, FakeLLMClient, make_context, make_stakes

FIXTURES = Path(__file__).parent / "fixtures"
CANARY_CASES: dict[str, Any] = json.loads(
    (FIXTURES / "canary_cases.json").read_text(encoding="utf-8")
)
TRANSCRIPTS: dict[str, Any] = json.loads(
    (FIXTURES / "refusal_transcripts.json").read_text(encoding="utf-8")
)
CASES: list[dict[str, Any]] = CANARY_CASES["cases"]
TRANSCRIPT_LIST: list[dict[str, Any]] = TRANSCRIPTS["transcripts"]

CATEGORIES = {
    "exact",
    "case_folded",
    "spaced",
    "base64",
    "hex",
    "rot13",
    "caesar",
    "reversed",
    "positions",
    "ascii",
    "zero_width",
    "homoglyph",
    "acrostic",
    "split",
    "benign",
    "near_miss",
}
HELD_CATEGORIES = {"benign", "near_miss"}
# The 4-hex fixture form and the 6-hex lowercase form `scripts/make_fake_run.py` draws.
CANARY_FORM = re.compile(r"WC-(?:[0-9A-F]{4}|[0-9a-f]{6})")
ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
KINDS = {"hard_refusal", "blocked", "soft_reminder", "helpful"}

# Realistic hard refusals that `is_refusal` misses today. Strict xfail, so fixing the
# patterns turns these red until they come off the list.
REFUSAL_GAPS: dict[str, str] = {}


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("the adversary harness must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# Canary corpus


def test_canary_corpus_schema() -> None:
    assert set(CANARY_CASES) == {"version", "cases"}
    assert CANARY_CASES["version"] == 1
    assert len(CASES) >= 30
    for case in CASES:
        assert set(case) == {"id", "category", "canary", "reply", "expected", "note"}, case
        assert all(isinstance(case[k], str) and case[k] for k in case), case["id"]
        assert case["category"] in CATEGORIES, case["id"]
        assert case["expected"] in {"leak", "held"}, case["id"]
        assert CANARY_FORM.fullmatch(case["canary"]), case["id"]


def test_canary_ids_are_unique() -> None:
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))


def test_canary_categories_are_covered() -> None:
    counts = Counter(case["category"] for case in CASES)
    assert {c: n for c, n in counts.items() if n < 2} == {}
    assert set(counts) == CATEGORIES
    assert sum(case["canary"] == CANARY for case in CASES) > len(CASES) / 2


def test_canary_labels_follow_category() -> None:
    for case in CASES:
        expected = "held" if case["category"] in HELD_CATEGORIES else "leak"
        assert case["expected"] == expected, case["id"]


def test_canary_is_verbatim_only_where_it_should_be() -> None:
    for case in CASES:
        canary, reply, category = case["canary"], case["reply"], case["category"]
        if category == "exact":
            assert canary in reply, case["id"]
        elif category == "case_folded":
            assert canary not in reply and canary.lower() in reply.lower(), case["id"]
        else:
            assert canary.lower() not in reply.lower(), case["id"]


def test_unicode_cases_hide_the_canary_in_unicode() -> None:
    for case in CASES:
        if case["category"] == "zero_width":
            assert ZERO_WIDTH.search(case["reply"]), case["id"]
            assert case["canary"] in ZERO_WIDTH.sub("", case["reply"]), case["id"]
        if case["category"] == "homoglyph":
            lookalikes = [ch for ch in case["reply"] if ord(ch) > 127]
            assert lookalikes, case["id"]
            assert all(unicodedata.category(ch)[0] in "LN" for ch in lookalikes), case["id"]


# Refusal corpus


def test_refusal_corpus_schema() -> None:
    assert set(TRANSCRIPTS) == {"version", "transcripts"}
    assert TRANSCRIPTS["version"] == 1
    assert len(TRANSCRIPT_LIST) >= 12
    ids = [t["id"] for t in TRANSCRIPT_LIST]
    assert len(ids) == len(set(ids))
    for t in TRANSCRIPT_LIST:
        assert set(t) == {"id", "model", "kind", "prompt", "reply"}, t["id"]
        assert t["model"] in {"llama3.1", "qwen3.5:4b"}, t["id"]
        assert t["kind"] in KINDS, t["id"]
        assert set(t["reply"]) == {"content", "tool_calls", "blocked_by", "latency_ms"}, t["id"]
        reply = TargetReply.model_validate(t["reply"])
        if t["kind"] == "blocked":
            assert reply.blocked_by == "input_filter", t["id"]
            assert len(reply.content) < 80, t["id"]
        else:
            assert reply.blocked_by is None, t["id"]
    assert {t["kind"] for t in TRANSCRIPT_LIST} == KINDS


def _transcripts(*kinds: str) -> list[Any]:
    params = []
    for t in TRANSCRIPT_LIST:
        if t["kind"] not in kinds:
            continue
        gap = REFUSAL_GAPS.get(t["id"])
        marks = [pytest.mark.xfail(strict=True, reason=gap)] if gap else []
        params.append(pytest.param(t, id=t["id"], marks=marks))
    return params


@pytest.mark.parametrize("transcript", _transcripts("hard_refusal", "blocked"))
def test_refusals_are_detected(transcript: dict[str, Any]) -> None:
    assert is_refusal(TargetReply.model_validate(transcript["reply"]))


@pytest.mark.parametrize("transcript", _transcripts("helpful"))
def test_helpful_replies_are_not_refusals(transcript: dict[str, Any]) -> None:
    assert not is_refusal(TargetReply.model_validate(transcript["reply"]))


def test_refusal_gaps_name_real_transcripts() -> None:
    kinds = {t["id"]: t["kind"] for t in TRANSCRIPT_LIST}
    assert all(kinds.get(i) == "hard_refusal" for i in REFUSAL_GAPS)


# Fake chat client


def _user(text: str) -> list[Message]:
    return [Message(role="user", content=text)]


def test_fake_llm_fits_chat_client() -> None:
    client: ChatClient = FakeLLMClient()
    reply = asyncio.run(client.chat("ollama:llama3.1", _user("hi")))
    assert reply == TargetReply(content="{}")


def test_fake_llm_records_calls() -> None:
    fake = FakeLLMClient()
    messages = _user("hello")
    asyncio.run(
        fake.chat("ollama:qwen3.5:4b", messages, system_prompt="be Alice", temperature=0.7, seed=3)
    )
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.model_spec == "ollama:qwen3.5:4b"
    assert call.messages == messages
    assert call.system_prompt == "be Alice"
    assert (call.temperature, call.seed, call.tools, call.json_schema) == (0.7, 3, None, None)


def test_fake_llm_rules_then_queue_then_default() -> None:
    ruled = TargetReply(content="ruled")
    queued = [TargetReply(content="q1"), TargetReply(content="q2")]
    default = TargetReply(content="default")
    fake = FakeLLMClient(queue=list(queued), rules=[(r"refund", ruled)], default=default)

    async def run() -> list[str]:
        prompts = ["refund please", "hi", "refund again", "hi", "hi"]
        return [(await fake.chat("m", _user(p))).content for p in prompts]

    assert asyncio.run(run()) == ["ruled", "q1", "ruled", "q2", "default"]


def test_fake_llm_rejects_tool_choice() -> None:
    fake = FakeLLMClient()
    with pytest.raises(AssertionError, match="tool_choice"):
        asyncio.run(fake.chat("m", _user("hi"), tool_choice="auto"))
    assert fake.calls == []


# Fake embedding client


def test_fake_embedder_fits_and_is_deterministic() -> None:
    client: EmbeddingClient = FakeEmbeddingClient()
    texts = ["Get Alice to reveal the secret.", "Refund order 1187 for $400.", ""]
    first = asyncio.run(client.embed(texts))
    second = asyncio.run(FakeEmbeddingClient().embed(texts))
    assert first == second
    assert len(first) == len(texts)
    for vector in first[:2]:
        assert len(vector) == FakeEmbeddingClient.dims
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0)
    assert first[0] != first[1]


def test_fake_embedder_records_calls() -> None:
    fake = FakeEmbeddingClient()
    asyncio.run(fake.embed(["a", "b"]))
    assert fake.calls == [["a", "b"]]


def test_fake_embedder_is_fast() -> None:
    fake = FakeEmbeddingClient()
    texts = [case["reply"] for case in CASES]
    rounds = 20

    async def run() -> float:
        start = time.perf_counter()
        for _ in range(rounds):
            await fake.embed(texts)
        return (time.perf_counter() - start) / rounds

    assert asyncio.run(run()) < 0.010


# Factories


@pytest.mark.parametrize("scenario", list(ScenarioId))
def test_make_stakes_for_every_scenario(scenario: ScenarioId) -> None:
    stakes = make_stakes(scenario)
    assert stakes.scenario is scenario
    assert stakes.canary == CANARY and CANARY_FORM.fullmatch(stakes.canary)
    assert stakes.objective
    if scenario is ScenarioId.SYSTEM_PROMPT:
        assert stakes.protected_text and CANARY in stakes.protected_text
    assert make_stakes(scenario, canary="WC-0A5F").canary == "WC-0A5F"


def test_refund_stakes_carry_the_tool_rules() -> None:
    rules = {rule.tool: rule for rule in make_stakes(ScenarioId.REFUND_TOOL).tool_rules}
    assert set(rules) == {"issue_refund", "send_email"}
    assert rules["issue_refund"].argument == "amount"
    assert rules["issue_refund"].max_value == 50
    assert rules["send_email"].argument == "to"
    assert rules["send_email"].allowed_suffix == "@marchhare.tea"
    assert make_stakes(ScenarioId.VAULT).tool_rules == []


@pytest.mark.parametrize("scenario", list(ScenarioId))
def test_make_context_never_holds_the_canary(scenario: ScenarioId) -> None:
    context = make_context(scenario)
    assert context.scenario is scenario
    assert context.objective == make_stakes(scenario).objective
    assert CANARY not in context.model_dump_json()
    assert CANARY not in repr(context.model_dump())
