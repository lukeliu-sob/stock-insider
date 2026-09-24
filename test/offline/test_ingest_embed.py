"""Offline tests for the embedding pipeline (TP-012a).

The embed function is injected (deterministic pseudo-embeddings);
no provider is ever contacted. Idempotence, per-batch failure
isolation, and the closed-run model refusal are pinned.

Implements: REQ-SI-FR-007, REQ-SI-INV-003 (ADR-003)
"""

from __future__ import annotations

import sqlite3

from stockinsider.data.ingest.embed import run_embed
from stockinsider.data.store.db import open_db
from stockinsider.data.store.vector import knn, pending_news


def _seed(conn: sqlite3.Connection, count: int, *, start: int = 0) -> None:
    with conn:
        for index in range(start + 1, start + count + 1):
            conn.execute(
                """
                INSERT INTO news (url_norm, url_raw, title, domain, published_at,
                                  fetched_at, source_query, symbol, relevance_score, kept)
                VALUES (?, ?, ?, 'reuters.com', ?, '2026-09-23T00:00:00+00:00',
                        'test', '0700.HK', 2.0, 1)
                """,
                (
                    f"https://example.com/{index}",
                    f"https://example.com/{index}",
                    f"Tencent headline number {index}",
                    f"2026091{index % 10}T090000Z",
                ),
            )


def _pseudo(texts: list[str]) -> list[list[float]]:
    out = []
    for text in texts:
        vector = [0.0] * 4
        for token in text.lower().split():
            vector[sum(ord(ch) for ch in token) % 4] += 1.0
        out.append(vector)
    return out


def test_embed_pending_idempotent(tmp_path) -> None:
    conn = open_db(tmp_path / "e.sqlite")
    _seed(conn, 5)
    first = run_embed(conn, _pseudo, "test-model")
    assert first["embedded"] == 5
    assert first["failed_batches"] == []
    second = run_embed(conn, _pseudo, "test-model")
    assert second["embedded"] == 0
    assert second["pending_before"] == 0
    assert knn(conn, "test-model", _pseudo(["tencent headline"])[0], k=1)[0].news_id in {
        1,
        2,
        3,
        4,
        5,
    }


def test_batch_failure_isolated_and_reported(tmp_path) -> None:
    conn = open_db(tmp_path / "e.sqlite")
    _seed(conn, 4)

    def flaky(texts: list[str]) -> list[list[float]]:
        if any("number 3" in text for text in texts):
            raise RuntimeError("provider hiccup")
        return _pseudo(texts)

    report = run_embed(conn, flaky, "test-model", batch_size=1)
    assert report["embedded"] == 3
    assert len(report["failed_batches"]) == 1
    assert report["failed_batches"][0]["error"].startswith("RuntimeError")
    assert [news_id for news_id, _ in pending_news(conn)] == [3]
    # a later clean run picks up the failed row
    retry = run_embed(conn, _pseudo, "test-model")
    assert retry["embedded"] == 1
    assert pending_news(conn) == []


def test_model_mismatch_fails_closed_mid_run(tmp_path) -> None:
    conn = open_db(tmp_path / "e.sqlite")
    _seed(conn, 6)
    run_embed(conn, _pseudo, "model-a")  # binds the table to model-a
    _seed(conn, 2, start=6)  # fresh rows give the second run something to refuse
    report = run_embed(conn, _pseudo, "model-b")
    assert report["embedded"] == 0
    assert report["failed_batches"] and "rebuild" in report["failed_batches"][0]["error"]
    # the bound model still queries cleanly
    assert knn(conn, "model-a", _pseudo(["tencent"])[0], k=2)


def test_empty_store_noop(tmp_path) -> None:
    conn = open_db(tmp_path / "e.sqlite")
    report = run_embed(conn, _pseudo, "test-model")
    assert report["embedded"] == 0
    assert report["pending_before"] == 0
