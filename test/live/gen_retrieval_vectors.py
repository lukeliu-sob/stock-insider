"""Live generator for the frozen QA-002 vectors (TP-036; never blocking).

Embeds every keep-labeled corpus title and every query once with the
configured embedding role (EMBEDDING_API_KEY / EMBEDDING_BASE_URL /
EMBEDDING_MODEL from the environment or .env) and writes
test/offline/fixtures/retrieval_vectors_v1.json with the model id,
the dims, and per text the SHA-256 of the exact embedded string.
The provider is reached only through the provider layer and its
egress gate. Any failure stops the run with nothing written.

Run: .venv/Scripts/python.exe test/live/gen_retrieval_vectors.py
TP-037 variants: add --variants. Only query vectors are embedded, for
the development and held-out sets under every variant of
test/offline/retrieval_variants.py, into
test/offline/fixtures/retrieval_query_vectors_tp037.json; the corpus
vectors of retrieval_vectors_v1.json are reused unchanged.

Implements: REQ-SI-QA-002, REQ-SI-FR-007 (ADR-003)
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "offline" / "fixtures"
CORPUS = FIXTURES / "news_corpus_v1.json"
QUERIES = FIXTURES / "retrieval_queries_v1.json"
OUTPUT = FIXTURES / "retrieval_vectors_v1.json"
HELDOUT = FIXTURES / "retrieval_queries_heldout_v1.json"
VARIANT_OUTPUT = FIXTURES / "retrieval_query_vectors_tp037.json"

#: Small batches: OpenAI-compatible embedding endpoints commonly cap
#: the inputs per call.
BATCH = 10


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _provider():
    from stockinsider.agent.providers import (
        OpenAICompatibleProvider,
        resolve_config,
        resolve_embedding_api_key,
    )

    config = resolve_config()
    key, source = resolve_embedding_api_key(config)
    if not config.embedding_base_url or key is None:
        print(f"embedding role not configured (base_url={config.embedding_base_url!r}, key {source})")
        return None, config
    return OpenAICompatibleProvider(config, api_key=key), config


def _embed_all(provider, texts: list[str]) -> list[list[float]] | None:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        batch = texts[start : start + BATCH]
        result = provider.embed(batch)
        if len(result) != len(batch):
            print(f"endpoint returned {len(result)} vectors for {len(batch)} texts; nothing written")
            return None
        vectors.extend(result)
    return vectors


def variants() -> int:
    sys.path.insert(0, str(FIXTURES.parent))
    from retrieval_variants import VARIANTS

    provider, config = _provider()
    if provider is None:
        return 1
    frozen = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if frozen["model_id"] != config.embedding_model:
        print(f"corpus vectors are {frozen['model_id']!r}, configured model is {config.embedding_model!r}")
        return 1
    sets = {
        "dev": json.loads(QUERIES.read_text(encoding="utf-8"))["queries"],
        "heldout": json.loads(HELDOUT.read_text(encoding="utf-8"))["queries"],
    }
    rows: list[tuple[str, str, int, str]] = []
    for name, transform in VARIANTS.items():
        for set_name, queries in sets.items():
            rows += [(name, set_name, query["id"], transform(query["query"])) for query in queries]
    vectors = _embed_all(provider, [text for *_rest, text in rows])
    if vectors is None:
        return 1
    if any(len(vector) != frozen["dims"] for vector in vectors):
        print("query vector dims differ from the corpus vectors; nothing written")
        return 1
    payload: dict = {
        "version": 1,
        "model_id": config.embedding_model,
        "dims": frozen["dims"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "variants": {},
    }
    for (name, set_name, query_id, text), vector in zip(rows, vectors):
        section = payload["variants"].setdefault(name, {}).setdefault(set_name, {})
        section[str(query_id)] = {"sha256": sha256(text), "vector": vector}
    VARIANT_OUTPUT.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {VARIANT_OUTPUT.name}: model={config.embedding_model} texts={len(rows)}")
    return 0


def main() -> int:
    provider, config = _provider()
    if provider is None:
        return 1

    corpus = [item for item in json.loads(CORPUS.read_text(encoding="utf-8"))["items"] if item["label"] == "keep"]
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]
    texts: list[tuple[str, int, str]] = [("corpus", item["id"], item["title"]) for item in corpus]
    texts += [("query", query["id"], query["query"]) for query in queries]

    embedded = _embed_all(provider, [text for _kind, _id, text in texts])
    if embedded is None:
        return 1
    vectors = embedded
    dims = len(vectors[0])
    if any(len(vector) != dims for vector in vectors):
        print("ragged vectors returned; nothing written")
        return 1

    payload = {
        "version": 1,
        "model_id": config.embedding_model,
        "dims": dims,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": {},
        "queries": {},
    }
    for (kind, item_id, text), vector in zip(texts, vectors):
        section = "corpus" if kind == "corpus" else "queries"
        payload[section][str(item_id)] = {"sha256": sha256(text), "vector": vector}
    OUTPUT.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.name}: model={config.embedding_model} dims={dims} texts={len(texts)}")
    return 0


if __name__ == "__main__":
    sys.exit(variants() if "--variants" in sys.argv[1:] else main())
