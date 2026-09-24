"""sqlite-vec vector store: news embeddings in the same SQLite file.

ADR-003: vec0 virtual table joined to ``news`` by rowid; brute-force
KNN is millisecond-class at corpus scale. The model-ID rule
(memory-design §2.3): the vector table is bound to one embedding
model identifier; insertions or queries with a different model_id
fail closed with the explicit rebuild-required error — mixed-model
vector spaces are impossible without a deliberate rebuild.

Fail-closed on the extension itself: when sqlite-vec cannot load,
every entry point raises VectorUnavailable (INV-003) — never a
silent fallback to keyword search.

Implements: REQ-SI-FR-007, REQ-SI-INV-003 (ADR-003)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

try:  # pragma: no cover - exercised via the loader seam below
    import sqlite_vec  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    sqlite_vec = None


class VectorUnavailable(RuntimeError):
    """sqlite-vec cannot serve this store (fail-closed).

    Implements: REQ-SI-INV-003 (ADR-003)
    """

    def __init__(self, detail: str) -> None:
        super().__init__(f"vector store unavailable: {detail}")
        self.detail = detail


class VectorModelMismatch(RuntimeError):
    """The table is bound to a different embedding model (fail-closed).

    Implements: REQ-SI-QA-003, REQ-SI-INV-003 (ADR-003)
    """

    def __init__(self, registered: str, requested: str) -> None:
        super().__init__(
            f"vector table bound to model '{registered}', request used "
            f"'{requested}'; a full index rebuild is required "
            "(memory-design §2.3) — refusing to mix embedding spaces"
        )
        self.registered = registered
        self.requested = requested


@dataclass(frozen=True)
class VectorHit:
    """One KNN result with its joined news metadata.

    Implements: REQ-SI-FR-007 (ADR-003)
    """

    news_id: int
    distance: float
    title: str
    url: str
    domain: str
    seendate: str
    bucket: str


def load_extension(conn: sqlite3.Connection) -> None:
    """Load sqlite-vec into ``conn`` or raise VectorUnavailable.

    Implements: REQ-SI-INV-003 (ADR-003)
    """
    if sqlite_vec is None:
        raise VectorUnavailable("sqlite-vec package not importable")
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (AttributeError, sqlite3.Error) as exc:  # pragma: no cover
        raise VectorUnavailable(f"extension load failed: {exc}") from exc


def _registered_model(conn: sqlite3.Connection) -> tuple[str, int] | None:
    try:
        row = conn.execute("SELECT model_id, dims FROM vec_registry WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return str(row["model_id"]), int(row["dims"])


def ensure_vec_table(conn: sqlite3.Connection, model_id: str, dims: int) -> None:
    """Create the vec0 table bound to ``model_id``; refuse model drift.

    Implements: REQ-SI-FR-007, REQ-SI-QA-003 (ADR-003)
    """
    load_extension(conn)
    registered = _registered_model(conn)
    if registered is not None:
        if registered[0] != model_id or registered[1] != dims:
            raise VectorModelMismatch(registered[0], model_id)
        return
    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_news"
            f" USING vec0(embedding float[{dims}])"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS vec_registry ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), model_id TEXT NOT NULL, "
            "dims INTEGER NOT NULL, built_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO vec_registry (id, model_id, dims, built_at) VALUES (1, ?, ?, ?)",
            (model_id, dims, built_at),
        )


def _vector_json(vector: Sequence[float]) -> str:
    return json.dumps([float(component) for component in vector])


def insert_vectors(conn: sqlite3.Connection, model_id: str, rows: Sequence[tuple[int, Sequence[float]]]) -> int:
    """Insert (news_id, vector) pairs; returns the count stored.

    Implements: REQ-SI-FR-007 (ADR-003)
    """
    if not rows:
        return 0
    load_extension(conn)
    registered = _registered_model(conn)
    if registered is None:
        raise VectorUnavailable("vec table not initialized (ensure_vec_table first)")
    if registered[0] != model_id:
        raise VectorModelMismatch(registered[0], model_id)
    payload = [(news_id, _vector_json(vector)) for news_id, vector in rows]
    expected_dims = registered[1]
    with conn:
        for news_id, blob in payload:
            stored = json.loads(blob)
            if len(stored) != expected_dims:
                raise VectorModelMismatch(registered[0], f"{model_id} with {len(stored)} dims")
            conn.execute(
                "INSERT OR REPLACE INTO vec_news(rowid, embedding) VALUES (?, ?)",
                (news_id, blob),
            )
    return len(payload)


def knn(
    conn: sqlite3.Connection,
    model_id: str,
    query_vector: Sequence[float],
    *,
    k: int = 5,
    bucket: str | None = None,
) -> list[VectorHit]:
    """Top-k nearest headlines; optional bucket filter (FR-007).

    Implements: REQ-SI-FR-007, REQ-SI-INV-003 (ADR-003)
    """
    load_extension(conn)
    registered = _registered_model(conn)
    if registered is None:
        raise VectorUnavailable("vec table not initialized")
    if registered[0] != model_id:
        raise VectorModelMismatch(registered[0], model_id)
    bucket_clause = ""
    bind: list[Any] = [_vector_json(query_vector), k]
    if bucket is not None:
        bucket_clause = "AND n.symbol = ? "
        bind.append(bucket)
    rows = conn.execute(
        f"""
        SELECT v.rowid AS news_id, v.distance AS distance,
               n.title AS title, n.url_raw AS url, n.domain AS domain,
               n.published_at AS seendate, n.symbol AS bucket
        FROM vec_news v JOIN news n ON n.news_id = v.rowid
        WHERE v.embedding MATCH ? AND k = ? {bucket_clause}
        ORDER BY v.distance
        """,
        bind,
    ).fetchall()
    return [
        VectorHit(
            news_id=int(row["news_id"]),
            distance=float(row["distance"]),
            title=str(row["title"]),
            url=str(row["url"]),
            domain=str(row["domain"]),
            seendate=str(row["seendate"]),
            bucket=str(row["bucket"]),
        )
        for row in rows
    ]


def pending_news(conn: sqlite3.Connection, *, limit: int = 128) -> list[tuple[int, str]]:
    """News rows without vectors, oldest first (embedding backlog).

    Implements: REQ-SI-FR-007 (ADR-003)
    """
    try:
        rows = conn.execute(
            """
            SELECT n.news_id AS news_id, n.title AS title
            FROM news n LEFT JOIN vec_news v ON v.rowid = n.news_id
            WHERE v.rowid IS NULL
            ORDER BY n.published_at, n.news_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.OperationalError:
        # vec table not created yet: every news row is pending
        rows = conn.execute(
            """
            SELECT news_id AS news_id, title AS title
            FROM news ORDER BY published_at, news_id LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [(int(row["news_id"]), str(row["title"])) for row in rows]


def prune_orphans(conn: sqlite3.Connection) -> int:
    """Delete vectors whose news rows are gone (retention follow-up).

    Implements: REQ-SI-FR-007 (ADR-003)
    """
    try:
        with conn:
            removed = conn.execute("DELETE FROM vec_news WHERE rowid NOT IN (SELECT news_id FROM news)").rowcount
    except sqlite3.OperationalError:
        return 0  # vec table not created yet: nothing to prune
    return int(removed or 0)
