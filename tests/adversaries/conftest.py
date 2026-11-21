"""Fixtures for Adversaries tests. The fakes live in `fakes.py`."""

from collections.abc import Callable

import pytest

from wonderland_court.contracts.models import AttackContext, Stakes

from .fakes import FakeEmbeddingClient, FakeLLMClient, make_context, make_stakes


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def fake_embedder() -> FakeEmbeddingClient:
    return FakeEmbeddingClient()


@pytest.fixture
def stakes_factory() -> Callable[..., Stakes]:
    return make_stakes


@pytest.fixture
def context_factory() -> Callable[..., AttackContext]:
    return make_context
