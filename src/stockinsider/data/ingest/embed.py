"""Embedding pipeline: pending news rows in, vectors stored (TP-012a).

The embed function is injected (data side imports no provider — the
dependency rule). Failures are explicit per batch and transactional:
a failed batch stores nothing for that batch and appears in the
report; other batches proceed. Idempotent: rows already carrying
vectors are skipped (via the store's pending-news query).

Implements: REQ-SI-FR-007, REQ-SI-INV-003 (ADR-003)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from stockinsider.data.store.vector import (
    VectorModelMismatch,
    ensure_vec_table,
    insert_vectors,
    pending_news,
    prune_orphans,
)

#: Embedding wire: texts in, equal-length float vectors out.
EmbedFn = Callable[[list[str]], list[list[float]]]


@dataclass
class EmbedReport:
    """The run's sole output surface (INV-003).

    Implements: REQ-SI-INV-003 (ADR-003)
    """

    ran_at: str
    model_id: str
    embedded: int = 0
    pending_before: int = 0
    orphan_vectors_removed: int = 0
    failed_batches: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Render for callers.

        Implements: REQ-SI-INV-003 (ADR-003)
        """
        return {
            "ran_at": self.ran_at,
            "model_id": self.model_id,
            "embedded": self.embedded,
            "pending_before": self.pending_before,
            "orphan_vectors_removed": self.orphan_vectors_removed,
            "failed_batches": list(self.failed_batches),
        }


def _dims_of(vectors: Sequence[Sequence[float]]) -> int:
    if not vectors:
        raise ValueError("embedding function returned no vectors for a non-empty batch")
    first = len(vectors[0])
    if any(len(vector) != first for vector in vectors):
        raise ValueError("embedding function returned ragged vectors")
    return first


def run_embed(
    conn: sqlite3.Connection,
    embed_fn: EmbedFn,
    model_id: str,
    *,
    batch_size: int = 16,
) -> dict[str, Any]:
    """Embed all pending news rows in batches; report as the sole output.

    Implements: REQ-SI-FR-007, REQ-SI-INV-003 (ADR-003)
    """
    report = EmbedReport(
        ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        model_id=model_id,
    )
    skipped: set[int] = set()
    while True:
        backlog = [(news_id, title) for news_id, title in pending_news(conn)
                   if news_id not in skipped]
        if report.pending_before == 0:
            report.pending_before = len(backlog)
        if not backlog:
            break
        batch = backlog[:batch_size]
        news_ids = [news_id for news_id, _ in batch]
        titles = [title for _, title in batch]
        try:
            vectors = embed_fn(titles)
            dims = _dims_of(vectors)
            ensure_vec_table(conn, model_id, dims)
            report.embedded += insert_vectors(conn, model_id, list(zip(news_ids, vectors)))
        except Exception as exc:  # batch-scoped isolation boundary
            report.failed_batches.append(
                {
                    "news_ids": news_ids,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            # A mismatched model fails the whole run closed; anything
            # else is batch-scoped (proceed with the next backlog slice,
            # which cannot contain the same rows — pending re-query
            # drops stored ones only).
            if isinstance(exc, VectorModelMismatch):
                break
            skipped.update(news_ids)
            continue
    report.orphan_vectors_removed = prune_orphans(conn)
    return report.as_dict()
