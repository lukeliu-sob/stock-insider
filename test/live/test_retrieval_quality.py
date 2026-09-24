"""Live retrieval-quality gate (FR-007 fit criterion; never blocking).

Gated on EVAL_SET=1. Seeds ~20 known-target headlines into a
throwaway store, embeds them plus 20 queries with the configured
real embedding model, and measures the top-5 hit rate. The >= 80
percent target is asserted here when the gate is explicitly
requested; results are printed for the evaluation logbook either
way (QA-002).

Implements: REQ-SI-FR-007, REQ-SI-QA-002 (ADR-003)
"""

from __future__ import annotations

import os

import pytest

from stockinsider.data.ingest.embed import run_embed
from stockinsider.data.store.db import open_db
from stockinsider.data.store.vector import knn

pytestmark = pytest.mark.skipif(
    os.environ.get("EVAL_SET") != "1",
    reason="live evaluation set: set EVAL_SET=1 to run (never blocking)",
)

TARGETS: list[tuple[str, str]] = [
    ("macro:fed", "Federal Reserve holds rates steady at September meeting"),
    ("macro:fed", "FOMC minutes show members split on timing of rate cuts"),
    ("macro:fed", "Federal Reserve signals patience on further easing"),
    ("macro:inflation", "CPI rises 2.4 percent year over year in August"),
    ("macro:inflation", "PCE inflation gauge cools to 2.1 percent"),
    ("macro:inflation", "US inflation expectations survey ticks down"),
    ("macro:china", "China GDP growth steadies at 4.9 percent in second quarter"),
    ("macro:china", "Caixin manufacturing PMI returns to expansion territory"),
    ("macro:hkma", "HKMA leaves base rate unchanged after Fed decision"),
    ("macro:hkma", "HIBOR fixings ease as Hong Kong liquidity improves"),
    ("macro:yuan", "USDCNY midpoint set firmer for third session"),
    ("macro:tariff", "New tariff list covers 38 product categories"),
    ("0700.HK", "Tencent wins approval for two mobile game titles"),
    ("0700.HK", "Tencent Holdings buys back shares worth HKD 20 billion"),
    ("0700.HK", "Tencent Music lifts parent outlook with paid-user growth"),
    ("AAPL.US", "Apple unveils on-device AI features for next iPhone"),
    ("AAPL.US", "Apple services revenue accelerates to record high"),
    ("HSI.INDX", "Hang Seng Index closes at three-week high on bank rally"),
    ("HSI.INDX", "Hang Seng tech gauge outperforms region in September"),
    ("NVDA.US", "NVIDIA data-center revenue beats on sovereign AI demand"),
]

QUERIES: list[str] = [
    "did the Fed change interest rates",
    "what did the FOMC minutes say",
    "central bank patience on rates",
    "latest consumer price index reading",
    "inflation cooling personal consumption expenditures",
    "expected inflation survey results",
    "China economic growth second quarter",
    "Chinese factory activity manufacturing index",
    "Hong Kong monetary authority base rate",
    "Hong Kong interbank offered rate liquidity",
    "yuan exchange rate against the dollar",
    "new tariffs on goods",
    "Tencent new game approvals",
    "Tencent share buyback program",
    "Tencent Music paying subscribers",
    "Apple artificial intelligence iPhone",
    "Apple services segment revenue",
    "Hang Seng Index performance banks",
    "Hang Seng technology index September",
    "NVIDIA data center chips demand",
]


def _provider():
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        pytest.skip("no provider key in environment")
    from stockinsider.agent.providers import OpenAICompatibleProvider, resolve_config

    config = resolve_config()
    if not config.embedding_base_url:
        pytest.skip("embedding base_url not configured")
    return OpenAICompatibleProvider(config, api_key=key), config.embedding_model


def test_retrieval_quality_top5(tmp_path) -> None:
    provider, model_id = _provider()
    conn = open_db(tmp_path / "eval.sqlite")
    with conn:
        for index, (bucket, title) in enumerate(TARGETS, start=1):
            conn.execute(
                """
                INSERT INTO news (url_norm, url_raw, title, domain, published_at,
                                  fetched_at, source_query, symbol, relevance_score, kept)
                VALUES (?, ?, ?, 'reuters.com', '20260918T090000Z',
                        '2026-09-23T00:00:00+00:00', 'eval', ?, 2.0, 1)
                """,
                (
                    f"https://eval.example/{index}",
                    f"https://eval.example/{index}",
                    title,
                    bucket,
                ),
            )
    report = run_embed(conn, provider.embed, model_id)
    assert report["embedded"] == len(TARGETS), report
    assert report["failed_batches"] == []

    vectors = provider.embed(QUERIES)
    hits = 0
    misses: list[tuple[str, list[str]]] = []
    for query, vector in zip(QUERIES, vectors):
        found = knn(conn, model_id, vector, k=5)
        titles = [hit.title for hit in found]
        expected = TARGETS[QUERIES.index(query)][1]
        if expected in titles:
            hits += 1
        else:
            misses.append((query, titles[:2]))
    rate = hits / len(QUERIES)
    print(f"\nretrieval quality: {hits}/{len(QUERIES)} = {rate:.2f} (target >= 0.80)")
    for query, near in misses:
        print(f"  MISS {query!r} -> {near}")
    assert rate >= 0.8, f"top-5 hit rate {rate:.2f} below the FR-007 fit criterion"
