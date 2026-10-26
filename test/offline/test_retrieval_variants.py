"""TP-037 stage 1: retrieval variants measured offline (E-012 evidence).

Every variant's query vectors were frozen once by the live generator
(--variants); the corpus vectors are the TP-036 frozen title vectors.
Each variant is scored on the development set (the TP-036 queries)
and the held-out set (written by a separate author), and the held-out
subset without the two exact duplicates of development queries is
reported alongside, as fixed in TP-037 before measurement. This suite
records evidence; it does not pick a winner (the owner does, stage 2).

Implements: REQ-SI-QA-002, REQ-SI-FR-007 (ADR-003)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from retrieval_variants import VARIANTS
from test_retrieval import GATE, K, _build_store, _knn_ranker, evaluate

FIXTURES = Path(__file__).parent / "fixtures"
#: Held-out queries whose text equals a development query (TP-037 check).
EXACT_DUPLICATES = {11, 17}


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus() -> list[dict[str, Any]]:
    return [item for item in _load("news_corpus_v1.json")["items"] if item["label"] == "keep"]


@pytest.fixture(scope="module")
def sets() -> dict[str, dict[str, Any]]:
    return {"dev": _load("retrieval_queries_v1.json"), "heldout": _load("retrieval_queries_heldout_v1.json")}


@pytest.fixture(scope="module")
def frozen_corpus() -> dict[str, Any]:
    return _load("retrieval_vectors_v1.json")


@pytest.fixture(scope="module")
def frozen_queries() -> dict[str, Any]:
    path = FIXTURES / "retrieval_query_vectors_tp037.json"
    assert path.exists(), "variant vectors missing: run gen_retrieval_vectors.py --variants (never skipped)"
    return json.loads(path.read_text(encoding="utf-8"))


def test_variant_vectors_match_every_query(sets, frozen_corpus, frozen_queries) -> None:
    assert frozen_queries["model_id"] == frozen_corpus["model_id"]
    assert frozen_queries["dims"] == frozen_corpus["dims"]
    problems: list[str] = []
    for name, transform in VARIANTS.items():
        for set_name, query_set in sets.items():
            stored = frozen_queries["variants"].get(name, {}).get(set_name, {})
            for query in query_set["queries"]:
                entry = stored.get(str(query["id"]))
                text = transform(query["query"])
                if entry is None:
                    problems.append(f"{name}/{set_name} {query['id']}: no frozen vector")
                elif entry["sha256"] != hashlib.sha256(text.encode("utf-8")).hexdigest():
                    problems.append(f"{name}/{set_name} {query['id']}: embedded text changed")
                elif len(entry["vector"]) != frozen_queries["dims"]:
                    problems.append(f"{name}/{set_name} {query['id']}: dims mismatch")
    assert problems == []


def test_heldout_set_integrity(corpus, sets) -> None:
    heldout, dev = sets["heldout"], sets["dev"]
    assert heldout["families"] == dev["families"]
    families = {name: set(ids) for name, ids in heldout["families"].items()}
    assert len(heldout["queries"]) >= 20
    assert {q["class"] for q in heldout["queries"]} == {q["class"] for q in dev["queries"]}
    for query in heldout["queries"]:
        assert query["target_id"] in families[query["family"]], query
    dev_texts = {q["query"].lower() for q in dev["queries"]}
    duplicates = {q["id"] for q in heldout["queries"] if q["query"].lower() in dev_texts}
    assert duplicates == EXACT_DUPLICATES


def _vectors(frozen_queries, variant: str, set_name: str) -> dict[str, list[float]]:
    return {qid: entry["vector"] for qid, entry in frozen_queries["variants"][variant][set_name].items()}


def _class_scores(rows, queries) -> dict[str, float]:
    by_id = {q["id"]: q["class"] for q in queries}
    scores: dict[str, list[float]] = {}
    for query_id, _hit, precision, _top in rows:
        scores.setdefault(by_id[query_id], []).append(precision)
    return {name: sum(values) / len(values) for name, values in sorted(scores.items())}


def test_variant_report(tmp_path, corpus, sets, frozen_corpus, frozen_queries) -> None:
    conn = _build_store(tmp_path, corpus, frozen_corpus)
    ranker = _knn_ranker(conn, frozen_corpus["model_id"])
    subsets = {
        "dev": sets["dev"]["queries"],
        "heldout": sets["heldout"]["queries"],
        "heldout-23": [q for q in sets["heldout"]["queries"] if q["id"] not in EXACT_DUPLICATES],
    }
    print(f"\nE-012 model={frozen_corpus['model_id']} k={K} gate={GATE}")
    table: dict[tuple[str, str], tuple[float, float]] = {}
    for variant in VARIANTS:
        for label, queries in subsets.items():
            set_name = "dev" if label == "dev" else "heldout"
            hit_rate, relevance, rows = evaluate(
                queries, sets[set_name]["families"], _vectors(frozen_queries, variant, set_name), ranker
            )
            table[(variant, label)] = (hit_rate, relevance)
            classes = " ".join(f"{name}={score:.2f}" for name, score in _class_scores(rows, queries).items())
            print(f"  {variant} {label:<10} hit@5={hit_rate:.3f} relevance@5={relevance:.3f} | {classes}")
            if label == "heldout":
                for query_id, hit, precision, top in rows:
                    print(f"      q{query_id:02d} hit={'Y' if hit else 'N'} p@5={precision:.1f} top={top}")
    assert len(table) == len(VARIANTS) * len(subsets)


def test_reversed_ranking_fails_for_every_variant(tmp_path, corpus, sets, frozen_corpus, frozen_queries) -> None:
    conn = _build_store(tmp_path, corpus, frozen_corpus)
    full = _knn_ranker(conn, frozen_corpus["model_id"], k=len(corpus))
    for variant in VARIANTS:
        hit_rate, relevance, _rows = evaluate(
            sets["heldout"]["queries"],
            sets["heldout"]["families"],
            _vectors(frozen_queries, variant, "heldout"),
            lambda vector: full(vector)[::-1],
        )
        assert hit_rate < GATE, variant
        assert relevance < GATE, variant
