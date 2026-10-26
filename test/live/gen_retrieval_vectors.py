"""Live generator for the frozen QA-002 vectors (TP-036; never blocking).

Embeds every keep-labeled corpus title and every query once with the
configured embedding role (EMBEDDING_API_KEY / EMBEDDING_BASE_URL /
EMBEDDING_MODEL from the environment or .env) and writes
test/offline/fixtures/retrieval_vectors_v1.json with the model id,
the dims, and per text the SHA-256 of the exact embedded string.
The provider is reached only through the provider layer and its
egress gate. Any failure stops the run with nothing written.

Run: .venv/Scripts/python.exe test/live/gen_retrieval_vectors.py

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

#: Small batches: OpenAI-compatible embedding endpoints commonly cap
#: the inputs per call.
BATCH = 10


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    from stockinsider.agent.providers import (
        OpenAICompatibleProvider,
        resolve_config,
        resolve_embedding_api_key,
    )

    config = resolve_config()
    key, source = resolve_embedding_api_key(config)
    if not config.embedding_base_url or key is None:
        print(f"embedding role not configured (base_url={config.embedding_base_url!r}, key {source})")
        return 1
    provider = OpenAICompatibleProvider(config, api_key=key)

    corpus = [item for item in json.loads(CORPUS.read_text(encoding="utf-8"))["items"] if item["label"] == "keep"]
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]
    texts: list[tuple[str, int, str]] = [("corpus", item["id"], item["title"]) for item in corpus]
    texts += [("query", query["id"], query["query"]) for query in queries]

    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        batch = [text for _kind, _id, text in texts[start : start + BATCH]]
        result = provider.embed(batch)
        if len(result) != len(batch):
            print(f"endpoint returned {len(result)} vectors for {len(batch)} texts; nothing written")
            return 1
        vectors.extend(result)
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
    sys.exit(main())
