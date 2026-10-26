"""QA-002 retrieval relevance suite over frozen real vectors (TP-036).

The corpus is the keep-labeled title corpus (news_corpus_v1.json);
the queries, topic families and targets are in
retrieval_queries_v1.json; the vectors were produced once by the
real embedding model (test/live/gen_retrieval_vectors.py) and are
loaded through the production store path (ensure_vec_table,
insert_vectors, knn), so the sqlite-vec KNN path ADR-003 asks QA-002
to cover is the code under test. A text whose hash no longer matches
its frozen vector, or a text with no vector, fails the suite by name:
it is never skipped and never re-embedded silently.

Gates (k = 5, no bucket filter): hit@5 >= 0.8 (FR-007 fit criterion)
and relevance@5 >= 0.8 (QA-002 metric). Per-query precision is
printed for the evaluation logbook.

Implements: REQ-SI-QA-002, REQ-SI-FR-007 (ADR-003)
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import sqlite3
from pathlib import Path
from typing import Any, Callable, Sequence

import pytest

from stockinsider.data.store.db import open_db
from stockinsider.data.store.vector import ensure_vec_table, insert_vectors, knn

FIXTURES = Path(__file__).parent / "fixtures"
K = 5
GATE = 0.8
MIN_QUERIES = 20
QUERY_CLASSES = {"official_name", "ticker", "alias", "macro", "paraphrase"}


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def corpus() -> list[dict[str, Any]]:
    return [item for item in _load("news_corpus_v1.json")["items"] if item["label"] == "keep"]


@pytest.fixture(scope="module")
def query_set() -> dict[str, Any]:
    return _load("retrieval_queries_v1.json")


@pytest.fixture(scope="module")
def frozen() -> dict[str, Any]:
    path = FIXTURES / "retrieval_vectors_v1.json"
    assert path.exists(), "frozen vectors missing: run test/live/gen_retrieval_vectors.py (never skipped)"
    return json.loads(path.read_text(encoding="utf-8"))


# -- fixture integrity -------------------------------------------------------


def fixture_problems(
    corpus: Sequence[dict[str, Any]],
    queries: Sequence[dict[str, Any]],
    frozen: dict[str, Any],
) -> list[str]:
    """Every reason the frozen vectors do not match the texts, by id."""
    problems: list[str] = []
    dims = frozen.get("dims")
    for section, rows in (
        ("corpus", [(item["id"], item["title"]) for item in corpus]),
        ("queries", [(query["id"], query["query"]) for query in queries]),
    ):
        stored = frozen.get(section, {})
        for item_id, text in rows:
            entry = stored.get(str(item_id))
            if entry is None:
                problems.append(f"{section} {item_id}: no frozen vector")
                continue
            if entry.get("sha256") != _sha256(text):
                problems.append(f"{section} {item_id}: text changed since the vectors were frozen")
            if len(entry.get("vector", [])) != dims:
                problems.append(f"{section} {item_id}: vector dims != {dims}")
    return problems


def test_frozen_vectors_match_every_text(corpus, query_set, frozen) -> None:
    assert fixture_problems(corpus, query_set["queries"], frozen) == []


def test_edited_corpus_text_fails_by_id(corpus, query_set, frozen) -> None:
    edited = copy.deepcopy(list(corpus))
    edited[0]["title"] += " (edited)"
    problems = fixture_problems(edited, query_set["queries"], frozen)
    assert problems == [f"corpus {edited[0]['id']}: text changed since the vectors were frozen"]


def test_query_without_vector_fails(corpus, query_set, frozen) -> None:
    extra = [*query_set["queries"], {"id": 999, "query": "unfrozen question"}]
    assert fixture_problems(corpus, extra, frozen) == ["queries 999: no frozen vector"]


def test_query_set_integrity(corpus, query_set) -> None:
    corpus_ids = {item["id"] for item in corpus}
    families = {name: set(ids) for name, ids in query_set["families"].items()}
    queries = query_set["queries"]
    assert len(queries) >= MIN_QUERIES
    assert {query["class"] for query in queries} == QUERY_CLASSES
    assert len({query["id"] for query in queries}) == len(queries)
    # families partition the corpus: every keep item judged exactly once
    assert sorted(i for ids in families.values() for i in ids) == sorted(corpus_ids)
    for query in queries:
        assert query["family"] in families, query
        assert query["target_id"] in families[query["family"]], query


# -- the store path ----------------------------------------------------------


def _build_store(tmp_path: Path, corpus, frozen) -> sqlite3.Connection:
    conn = open_db(tmp_path / "retrieval.sqlite")
    with conn:
        for item in corpus:
            conn.execute(
                """
                INSERT INTO news (news_id, url_norm, url_raw, title, domain, published_at,
                                  fetched_at, source_query, symbol, relevance_score, kept)
                VALUES (?, ?, ?, ?, ?, ?, '2026-10-26T00:00:00+00:00', 'qa-002', 'qa', 2.0, 1)
                """,
                (item["id"], item["url"], item["url"], item["title"], item["domain"], item["seendate"]),
            )
    ensure_vec_table(conn, frozen["model_id"], frozen["dims"])
    rows = [(item["id"], frozen["corpus"][str(item["id"])]["vector"]) for item in corpus]
    assert insert_vectors(conn, frozen["model_id"], rows) == len(corpus)
    return conn


Ranker = Callable[[list[float]], list[int]]


def _knn_ranker(conn: sqlite3.Connection, model_id: str, k: int = K) -> Ranker:
    return lambda vector: [hit.news_id for hit in knn(conn, model_id, vector, k=k)]


def evaluate(
    queries: Sequence[dict[str, Any]],
    families: dict[str, list[int]],
    query_vectors: dict[str, list[float]],
    ranker: Ranker,
) -> tuple[float, float, list[tuple[int, bool, float, list[int]]]]:
    """(hit@5, relevance@5, per-query rows) for one ranking function."""
    rows: list[tuple[int, bool, float, list[int]]] = []
    for query in queries:
        top = ranker(query_vectors[str(query["id"])])[:K]
        relevant = set(families[query["family"]])
        hit = query["target_id"] in top
        precision = sum(1 for news_id in top if news_id in relevant) / K
        rows.append((query["id"], hit, precision, top))
    hit_rate = sum(1 for _id, hit, _p, _top in rows if hit) / len(rows)
    relevance = sum(p for _id, _hit, p, _top in rows) / len(rows)
    return hit_rate, relevance, rows


def _query_vectors(frozen) -> dict[str, list[float]]:
    return {qid: entry["vector"] for qid, entry in frozen["queries"].items()}


def test_store_registration_matches_frozen_model(tmp_path, corpus, frozen) -> None:
    conn = _build_store(tmp_path, corpus, frozen)
    row = conn.execute("SELECT model_id, dims FROM vec_registry WHERE id = 1").fetchone()
    assert (row["model_id"], row["dims"]) == (frozen["model_id"], frozen["dims"])


# -- the gates ---------------------------------------------------------------


def _measure(tmp_path, corpus, query_set, frozen) -> tuple[float, float]:
    conn = _build_store(tmp_path, corpus, frozen)
    hit_rate, relevance, rows = evaluate(
        query_set["queries"], query_set["families"], _query_vectors(frozen), _knn_ranker(conn, frozen["model_id"])
    )
    print(f"\nQA-002 model={frozen['model_id']} dims={frozen['dims']} queries={len(rows)}")
    print(f"hit@5={hit_rate:.3f} (gate {GATE}) relevance@5={relevance:.3f} (gate {GATE})")
    for query_id, hit, precision, top in rows:
        print(f"  q{query_id:02d} hit={'Y' if hit else 'N'} precision@5={precision:.1f} top={top}")
    return hit_rate, relevance


def test_hit_at_5_gate(tmp_path, corpus, query_set, frozen) -> None:
    hit_rate, _relevance = _measure(tmp_path, corpus, query_set, frozen)
    assert hit_rate >= GATE, f"hit@5 {hit_rate:.3f} below the FR-007 fit criterion"


@pytest.mark.xfail(
    strict=True,
    reason="owner decision 2026-10-26 (D10a): QA-002 not met (0.768 < 0.8, E-011; E-012 no fix); residual accepted, DE-17",
)
def test_relevance_at_5_gate(tmp_path, corpus, query_set, frozen) -> None:
    # QA-002 threshold, measured once on the frozen vectors: 0.768 (E-011).
    # Owner decision on 2026-10-26 (in session): land the suite with the miss
    # recorded and try a retrieval improvement under its own plan (TP-037).
    # The assertion is kept as written and marked expected-failure (strict),
    # so the unmet threshold shows in every run. If it ever passes, the marker
    # must be removed on purpose. The D1 v2 precondition stays unmet meanwhile.
    _hit_rate, relevance = _measure(tmp_path, corpus, query_set, frozen)
    assert relevance >= GATE, f"relevance@5 {relevance:.3f} below the QA-002 threshold"


def test_reversed_ranking_fails_both_gates(tmp_path, corpus, query_set, frozen) -> None:
    conn = _build_store(tmp_path, corpus, frozen)
    full = _knn_ranker(conn, frozen["model_id"], k=len(corpus))
    hit_rate, relevance, _rows = evaluate(
        query_set["queries"], query_set["families"], _query_vectors(frozen), lambda vector: full(vector)[::-1]
    )
    assert hit_rate < GATE
    assert relevance < GATE


def test_random_query_vectors_fail_both_gates(tmp_path, corpus, query_set, frozen) -> None:
    conn = _build_store(tmp_path, corpus, frozen)
    rng = random.Random(36)
    noise = {
        qid: [rng.uniform(-1.0, 1.0) for _ in range(frozen["dims"])] for qid in frozen["queries"]
    }
    hit_rate, relevance, _rows = evaluate(
        query_set["queries"], query_set["families"], noise, _knn_ranker(conn, frozen["model_id"])
    )
    assert hit_rate < GATE
    assert relevance < GATE
