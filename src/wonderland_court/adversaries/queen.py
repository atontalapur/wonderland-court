"""Registry entry point for the Queen of Hearts: `registry.load_judge` imports this module."""

from __future__ import annotations

from .judge import QueenJudge
from .ports import ModelClient, ModelConfig


def build_judge(*, config: ModelConfig, client: ModelClient) -> QueenJudge:
    """The four-layer judge, using `client` for both the layer-4 LLM and layer-3 embeddings."""
    return QueenJudge(
        llm=client,
        embedder=client,
        judge_model=config.judge_model,
        embed_model=config.embed_model,
    )
