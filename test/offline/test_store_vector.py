"""Offline tests for the vector store (sqlite-vec, TP-012a).

Deterministic pseudo-embeddings prove KNN mechanics, bucket
filters, the model-ID refusal, and pending/prune bookkeeping. The
real-model retrieval-quality gate lives in the live suite.

Implements: REQ-SI-FR-007, REQ-SI-QA-003 (ADR-003)
"""

from __future__ import annotations

import sqlite3

import pytest

from stockinsider.data.store.db import open_db
from stockinsider.data.store.vector import (
    VectorModelMismatch,
    ensure_vec_table,
    insert_vectors,
    knn,
    pending_news,
    prune_orphans,
)


def _pseudo(text: str, dims: int = 4) -> list[float]:
    """Deterministic token-hashed vector (test-only)."""
    vector = [0.0] * dims
    for token in text.lower().split():
        index = sum(ord(ch) for ch in token) % dims  # stable across runs
        vector[index] += 1.0
    return vector


def _seed_news(conn: sqlite3.Connection, rows: list[tuple[str, str, str]]) -> None:
    with conn:
        for index, (symbol, title, published) in enumerate(rows, start=1):
            conn.execute(
                """
                INSERT INTO news (url_norm, url_raw, title, domain, published_at,
                                  fetched_at, source_query, symbol, relevance_score, kept)
                VALUES (?, ?, ?, 'reuters.com', ?, '2026-09-23T00:00:00+00:00',
                        'test', ?, 2.0, 1)
                """,
                (f"https://example.com/{index}", f"https://example.com/{index}", title, published, symbol),
            )


def test_vec_table_knn_and_bucket_filter(tmp_path) -> None:
    conn = open_db(tmp_path / "v.sqlite")
    _seed_news(
        conn,
        [
            ("0700.HK", "Tencent wins game approval", "20260918T090000Z"),
            ("0700.HK", "Tencent music margins improve", "20260919T090000Z"),
            ("macro:fed", "Federal Reserve holds rates steady", "20260918T100000Z"),
        ],
    )
    ensure_vec_table(conn, "test-model", 4)
    # constructed orthogonal vectors: ordering is by design, not by token luck
    rows = [
        (1, [1.0, 0.0, 0.0, 0.0]),
        (2, [0.0, 1.0, 0.0, 0.0]),
        (3, [0.9, 0.1, 0.0, 0.0]),
    ]
    assert insert_vectors(conn, "test-model", rows) == 3

    hits = knn(conn, "test-model", [1.0, 0.0, 0.0, 0.0], k=2)
    assert len(hits) == 2
    assert [hit.news_id for hit in hits] == [1, 3]
    assert hits[0].distance <= hits[1].distance
    assert hits[0].title == "Tencent wins game approval"
    assert hits[0].bucket == "0700.HK"

    scoped = knn(conn, "test-model", [1.0, 0.0, 0.0, 0.0], k=5, bucket="macro:fed")
    assert [hit.news_id for hit in scoped] == [3]


def test_model_id_refusal(tmp_path) -> None:
    conn = open_db(tmp_path / "v.sqlite")
    _seed_news(conn, [("0700.HK", "Tencent wins game approval", "20260918T090000Z")])
    ensure_vec_table(conn, "model-a", 4)
    insert_vectors(conn, "model-a", [(1, _pseudo("x"))])

    with pytest.raises(VectorModelMismatch):
        insert_vectors(conn, "model-b", [(2, _pseudo("y"))])
    with pytest.raises(VectorModelMismatch):
        knn(conn, "model-b", _pseudo("y"))
    with pytest.raises(VectorModelMismatch):
        ensure_vec_table(conn, "model-b", 4)
    # dims drift is also a mismatch
    with pytest.raises(VectorModelMismatch):
        ensure_vec_table(conn, "model-a", 8)
    # the bound model still works
    assert knn(conn, "model-a", _pseudo("x"), k=1)[0].news_id == 1


def test_pending_and_prune(tmp_path) -> None:
    conn = open_db(tmp_path / "v.sqlite")
    _seed_news(
        conn,
        [
            ("0700.HK", "Tencent wins game approval", "20260918T090000Z"),
            ("0700.HK", "Tencent buys back shares", "20260917T090000Z"),
        ],
    )
    ensure_vec_table(conn, "m", 4)
    pending = pending_news(conn)
    assert [news_id for news_id, _ in pending] == [2, 1]  # oldest first
    insert_vectors(conn, "m", [(1, _pseudo("Tencent wins"))])
    assert [news_id for news_id, _ in pending_news(conn)] == [2]
    # retention removed news 2 before it was embedded
    with conn:
        conn.execute("DELETE FROM news WHERE news_id = 2")
    assert pending_news(conn) == []
    # an orphan vector (if any) is pruned; count reflects removal
    with conn:
        conn.execute("INSERT INTO vec_news(rowid, embedding) VALUES (99, '[0.0, 0.0, 0.0, 0.0]')")
    assert prune_orphans(conn) == 1
    assert prune_orphans(conn) == 0
