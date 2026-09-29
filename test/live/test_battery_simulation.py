"""TP-017 PR-3b: the 13-turn audit battery as a live eval set (E-007).

Gated by EVAL_SET=1 (live tests never block CI). Replicates the
second audit's conversation shape; per-turn post-check outcomes
are printed for the evaluation logbook. Residual classes are
documented, not asserted away.

Implements: REQ-SI-QA-001 (ADR-001)
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("EVAL_SET") != "1", reason="live battery (set EVAL_SET=1)"
)

TURNS = [
    "what is the latest close of 0700.HK?",
    "will it rise next month?",
    "what are its volatility and max drawdown?",
    "summarize recent news around it with dates",
    "compare 0700.HK and 1211.HK closes",
    "what was the close I asked about at the start?",
]


def test_battery_postcheck_outcomes(tmp_path) -> None:
    from stockinsider.agent.providers import OpenAICompatibleProvider, resolve_api_key, resolve_config
    from stockinsider.agent.repl import build_registry
    from stockinsider.agent.session import SessionStore
    from stockinsider.data import open_data_store
    from stockinsider.agent.loop import TurnEngine

    store = SessionStore(root=tmp_path / "sessions")
    data_store = open_data_store()
    config = resolve_config()
    key, _ = resolve_api_key()
    provider = OpenAICompatibleProvider(config, api_key=key)
    registry = build_registry(store, data_store, None)
    engine = TurnEngine(store, registry, provider)
    record = store.create(profile="standard")
    outcomes = []
    for question in TURNS:
        outcome = engine.run_turn(
            record["session_id"],
            question,
            profile="standard",
            render=lambda s: None,
            progress=lambda s: None,
        )
        outcomes.append((question, outcome.quarantined, outcome.displayed[:80]))
    for question, quarantined, head in outcomes:
        print(f"{'QUARANTINED' if quarantined else 'pass':11} | {question} | {head}")
    # the battery is a measurement, not a hard gate: every outcome is
    # printed for the logbook; zero-crash IS asserted
    assert all(isinstance(q, bool) for _, q, _ in outcomes)
