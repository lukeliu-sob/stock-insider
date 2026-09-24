"""Live embedding smoke (one round trip; never blocking).

Gated on EMBED_SMOKE=1. Verifies the provider embedding wire end to
end and records the real vector dimensionality for the vector store.

Implements: REQ-SI-FR-007, REQ-SI-QA-002 (ADR-001)
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("EMBED_SMOKE") != "1",
    reason="live smoke: set EMBED_SMOKE=1 to run (never blocking)",
)


def test_embedding_round_trip() -> None:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        pytest.skip("no provider key in environment")
    from stockinsider.agent.providers import OpenAICompatibleProvider, resolve_config

    config = resolve_config()
    if not config.embedding_base_url:
        pytest.skip("embedding base_url not configured")
    provider = OpenAICompatibleProvider(config, api_key=key)
    vectors = provider.embed(["Hang Seng Index closes higher", "Federal Reserve decision"])
    assert len(vectors) == 2
    assert len(vectors[0]) == len(vectors[1])
    assert len(vectors[0]) > 0
    assert any(component != 0.0 for component in vectors[0])
    print(f"\nembedding smoke ok: model={config.embedding_model} dims={len(vectors[0])}")
