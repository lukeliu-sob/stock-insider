"""EODHD news ingestion (TP-014): primary symbol-scoped source.

Same vendor seam as the market path (ADR-002): the classified
transport in, EODHD-shaped items out. The five-stage machinery is
reused at the primitive level (structural gates, scoring with the
vendor-entity refinement, dedup keys, survivor order); this module
adds the EODHD item mapping (ISO date to the sortable seendate
form, vendor-stated English), stores content and sentiment
verbatim as vendor evidence (never merged into scoring), and
shares the market call budget — one request per active watchlist
symbol per run, deferred on budget exhaustion like any EODHD call.

Implements: REQ-SI-FR-003, REQ-SI-FR-007, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from stockinsider.data.ingest.http import FetchResult, Transport, stdlib_fetch
from stockinsider.data.ingest.news import (
    DUP_WINDOW_DAYS,
    RETENTION_DAYS,
    _iso,
    _seendate_str,
    _set_news_cursor,
    watchlist_entries,
)
from stockinsider.data.ingest.newsfilter import (
    GateFailure,
    jaccard,
    normalize_url,
    score_against_symbol,
    structural_gates,
    survivor_rank,
    title_token_set,
)
from stockinsider.shared.envfile import env_value

EODHD_NEWS_BASE = "https://eodhd.com/api/news"
EODHD_KEY_ENV = "EODHD_API_KEY"

#: sync_state track key for the EODHD news cursor.
EODHD_NEWS_TRACK = "news:eodhd"

#: One bounded page per symbol per run (design: one request per symbol).
FETCH_LIMIT = 50

#: Vendor-stated English coverage (recorded in TP-014; no runtime guessing).
VENDOR_LANGUAGE = "English"


class EodhdNewsError(RuntimeError):
    """A classified EODHD news failure.

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind  # "http" | "auth" | "throttle" | "transport" | "malformed"
        self.detail = detail


class EodhdNewsAdapter:
    """Fetch one symbol's news page through the shared transport seam.

    Implements: REQ-SI-FR-003, REQ-SI-INV-003 (ADR-002)
    """

    def __init__(self, transport: Transport | None = None, api_key: str | None = None) -> None:
        self._transport: Transport = transport if transport is not None else stdlib_fetch
        self._api_key: str | None = api_key if api_key is not None else (env_value(EODHD_KEY_ENV) or None)

    def fetch(self, symbol: str, *, limit: int = FETCH_LIMIT) -> list[dict[str, Any]]:
        """Return the vendor's news items for one symbol.

        Implements: REQ-SI-FR-003, REQ-SI-INV-003 (ADR-002)
        """
        if not self._api_key:
            raise EodhdNewsError("auth", f"{EODHD_KEY_ENV} is not configured")
        params = {
            "s": symbol,
            "api_token": self._api_key,
            "fmt": "json",
            "offset": "0",
            "limit": str(limit),
        }
        try:
            result: FetchResult = self._transport(EODHD_NEWS_BASE, params)
        except EodhdNewsError:
            raise
        except (OSError, RuntimeError) as exc:
            if "429" in str(exc):
                raise EodhdNewsError("throttle", f"HTTP 429 for {symbol}") from exc
            raise EodhdNewsError("transport", f"{type(exc).__name__}: {exc}") from exc
        if result.status == 429:
            raise EodhdNewsError("throttle", f"HTTP 429 for {symbol}")
        if result.status in (401, 403):
            raise EodhdNewsError("auth", f"HTTP {result.status} for {symbol}")
        if result.status == 402:
            raise EodhdNewsError("http", f"HTTP 402 capacity-is-bought for {symbol}")
        if result.status != 200:
            raise EodhdNewsError("http", f"HTTP {result.status} for {symbol}")
        try:
            payload = json.loads(result.body)
        except json.JSONDecodeError as exc:
            raise EodhdNewsError("malformed", f"body is not JSON: {exc}") from exc
        if not isinstance(payload, list) or any(not isinstance(i, dict) for i in payload):
            raise EodhdNewsError("malformed", "payload is not a list of objects")
        return list(payload)


def _iso_to_seendate(raw: object) -> str | None:
    """Vendor ISO 8601 date -> the sortable GDELT-style form."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def map_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Vendor item -> the pipeline's gate/scoring shape.

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    link = raw.get("link")
    domain = urlparse(link).netloc.lower() if isinstance(link, str) else ""
    return {
        "title": raw.get("title"),
        "url": link,
        "domain": domain,
        "seendate": _iso_to_seendate(raw.get("date")),
        "language": VENDOR_LANGUAGE,
        # vendor extras, stored verbatim (TP-014: evidence, never scoring input)
        "content": raw.get("content"),
        "sentiment": raw.get("sentiment"),
        "symbols": raw.get("symbols") or [],
        "tags": raw.get("tags") or [],
    }


def _insert_eodhd(
    conn: sqlite3.Connection,
    bucket: str,
    query: str,
    item: dict[str, Any],
    url_norm: str,
    score: Any,
    now: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO news
            (url_norm, url_raw, title, domain, published_at, fetched_at, source_query,
             symbol, relevance_score, kept, content, sentiment, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'eodhd')
        """,
        (
            url_norm,
            item["url"],
            item["title"],
            item.get("domain") or "",
            item["seendate"],
            _iso(now),
            query,
            bucket,
            score.score,
            item.get("content"),
            json.dumps(item.get("sentiment")) if item.get("sentiment") is not None else None,
        ),
    )


def run_eodhd_news_sync(
    conn: sqlite3.Connection,
    adapter: EodhdNewsAdapter | None = None,
    *,
    now: datetime | None = None,
    budget: Any | None = None,
) -> dict[str, Any]:
    """Fetch and store news per active watchlist symbol (TP-014).

    Per-symbol failures are isolated and reported; the shared EODHD
    budget is spent per request with deferred semantics on
    exhaustion. Cross-source dedup rides the existing keys.

    Implements: REQ-SI-FR-003, REQ-SI-FR-007, REQ-SI-INV-003 (ADR-002)
    """
    from stockinsider.data.ingest.budget import CallBudget

    adapter = adapter if adapter is not None else EodhdNewsAdapter()
    now = now if now is not None else datetime.now(timezone.utc)
    budget = budget if budget is not None else CallBudget(conn)
    window_start = now - timedelta(days=RETENTION_DAYS)
    results: list[dict[str, Any]] = []
    spent = 0
    for entry in watchlist_entries(conn):
        if not budget.try_spend(1):
            results.append(
                {
                    "bucket": entry.canonical_symbol,
                    "status": "deferred",
                    "error": "daily call budget exhausted",
                }
            )
            continue
        spent += 1
        query = f"eodhd:s={entry.canonical_symbol}"
        try:
            raw_items = adapter.fetch(entry.canonical_symbol)
        except EodhdNewsError as exc:
            results.append({"bucket": entry.canonical_symbol, "status": exc.kind, "error": str(exc)})
            continue
        counts = {"kept_new": 0, "dups": 0, "quarantined": 0, "rejected": 0}
        dup_cutoff = _seendate_str(now - timedelta(days=DUP_WINDOW_DAYS))
        with conn:
            for raw in raw_items:
                item = map_item(raw)
                gate = structural_gates(item, window_start=window_start, window_end=now)
                if not gate.ok:
                    assert gate.failure is not None
                    failure: GateFailure = gate.failure
                    conn.execute(
                        """
                        INSERT INTO news_quarantine
                            (bucket, url_norm, title, domain, published_at, fetched_at,
                             source_query, reason, failing_gate, detail, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'eodhd')
                        """,
                        (
                            entry.canonical_symbol,
                            item["url"] if isinstance(item["url"], str) else "",
                            item["title"] if isinstance(item["title"], str) else "",
                            item["domain"] if isinstance(item["domain"], str) else "",
                            item["seendate"] if isinstance(item["seendate"], str) else "",
                            _iso(now),
                            query,
                            failure.gate,
                            failure.gate,
                            failure.detail,
                        ),
                    )
                    counts["quarantined"] += 1
                    continue
                entities = [str(s) for s in item["symbols"]]
                score = score_against_symbol(str(item["title"]), item.get("domain"), entry, entities=entities)
                if not score.keep:
                    counts["rejected"] += 1
                    continue
                url_norm = normalize_url(str(item["url"]))
                incoming = {
                    "source_tier": score.source_tier,
                    "seendate": item["seendate"],
                }
                row_a = conn.execute(
                    "SELECT news_id, source_tier, published_at FROM news WHERE symbol = ? AND url_norm = ?",
                    (entry.canonical_symbol, url_norm),
                ).fetchone()
                if row_a is not None:
                    stored = {
                        "source_tier": row_a["source_tier"],
                        "seendate": row_a["published_at"],
                    }
                    if survivor_rank(incoming) < survivor_rank(stored):
                        conn.execute("DELETE FROM news WHERE news_id = ?", (row_a["news_id"],))
                        _insert_eodhd(conn, entry.canonical_symbol, query, item, url_norm, score, now)
                    counts["dups"] += 1
                    continue
                tokens = title_token_set(str(item["title"]))
                duplicate = False
                for cand in conn.execute(
                    "SELECT news_id, source_tier, published_at, title FROM news WHERE symbol = ? AND published_at >= ?",
                    (entry.canonical_symbol, dup_cutoff),
                ).fetchall():
                    if jaccard(tokens, title_token_set(cand["title"])) >= 0.8:
                        duplicate = True
                        cand_rank = {
                            "source_tier": cand["source_tier"],
                            "seendate": cand["published_at"],
                        }
                        if survivor_rank(incoming) < survivor_rank(cand_rank):
                            conn.execute("DELETE FROM news WHERE news_id = ?", (cand["news_id"],))
                            _insert_eodhd(conn, entry.canonical_symbol, query, item, url_norm, score, now)
                        break
                if duplicate:
                    counts["dups"] += 1
                    continue
                _insert_eodhd(conn, entry.canonical_symbol, query, item, url_norm, score, now)
                counts["kept_new"] += 1
        results.append({"bucket": entry.canonical_symbol, "status": "ok", **counts})
    _set_news_cursor(conn, now.date().isoformat(), now)  # informational; dedup is the idempotence
    return {
        "ran_at": _iso(now),
        "source": "eodhd",
        "calls_spent": spent,
        "queries": results,
    }


def eodhd_news_status(conn: sqlite3.Connection) -> dict[str, Any]:
    """Per-source counts for status surfaces (TP-014).

    Implements: REQ-SI-FR-007 (ADR-002)
    """
    rows = conn.execute("SELECT source, COUNT(*) AS n FROM news GROUP BY source ORDER BY source").fetchall()
    return {"by_source": {row["source"] or "gdelt": row["n"] for row in rows}}
