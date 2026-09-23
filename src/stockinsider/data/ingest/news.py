"""GDELT news ingestion: query construction, fetch, storage, retention.

Transport-seamed like the market path (ADR-002): a Transport callable in,
classified failures out, transactional writes per batch. The filter
(S1/S2/S3) lives in newsfilter.py — this module composes it into the
corpus pipeline: S0 queries per watchlist symbol and per macro keyword
group (design D4), S4 storage with dedup application and quarantine
visibility, S5 two-year retention. The news track runs after the market
track with failure isolation (one track failing never fails the other).

Throttle discipline (live-probe evidence, 2026-09-21): bursts earn 429s
with cooldowns exceeding four minutes — on the first throttle the
remaining queries are aborted for the run and the cursor is not
advanced, so the next sync re-covers the window instead of hammering.

Implements: REQ-SI-FR-003, REQ-SI-FR-007, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from stockinsider.data.ingest.http import FetchResult, Transport, stdlib_fetch

from stockinsider.data.ingest.newsfilter import (
    GateFailure,
    MacroGroup,
    SymbolEntry,
    jaccard,
    normalize_url,
    score_against_macro,
    score_against_symbol,
    structural_gates,
    survivor_rank,
    title_token_set,
)

#: Structural type for the score payload passed to _insert_article.
ScoreResultLike = Any

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

#: sync_state track key for the news cursor.
NEWS_TRACK = "news"

#: GDELT's rolling window caps the initial corpus at three months (D3).
INITIAL_TIMESPAN = "3mon"

#: One query per bucket per sync; polite upper bound on records.
MAXRECS = 75

#: Inter-query pacing (design §8; probe-verified necessity).
INTER_QUERY_SLEEP = 5.0

#: Two-year rolling retention (design S5).
RETENTION_DAYS = 730

#: Key B duplicates are searched within this window (design S3).
DUP_WINDOW_DAYS = 14

#: Macro keyword groups — design §7 D4 (owner-confirmed 2026-09-17).
MACRO_GROUPS: tuple[MacroGroup, ...] = (
    MacroGroup("fed", ("federal reserve", "fed rate", "fomc", "the fed")),
    MacroGroup("inflation", ("cpi", "pce", "inflation")),
    MacroGroup("china", ("china gdp", "china pmi", "caixin")),
    MacroGroup("hkma", ("hkma", "base rate", "hibor")),
    MacroGroup("yuan", ("usdcny", "yuan")),
    MacroGroup("tariff", ("tariff", "tariffs")),
)


class NewsFetchError(RuntimeError):
    """A classified GDELT fetch failure.

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind  # "http" | "throttle" | "malformed"
        self.detail = detail


def _seendate_str(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%SZ")


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


class GdeltNewsAdapter:
    """Fetch and parse one GDELT DOC 2.0 artlist query.

    Implements: REQ-SI-FR-003, REQ-SI-INV-003 (ADR-002)
    """

    def __init__(self, transport: Transport | None = None) -> None:
        self._transport: Transport = transport if transport is not None else stdlib_fetch

    def fetch(self, query: str, timespan: str) -> list[dict[str, Any]]:
        """Return raw artlist items; raise NewsFetchError on failure.

        Implements: REQ-SI-FR-003, REQ-SI-INV-003 (ADR-002)
        """
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecs": str(MAXRECS),
            "timespan": timespan,
        }
        try:
            result: FetchResult = self._transport(GDELT_BASE, params)
        except NewsFetchError:
            raise
        except (OSError, RuntimeError) as exc:
            # The stdlib seam raises TransportError instead of returning
            # non-200 statuses (BD-013): recover the code from the message
            # so throttle semantics survive the seam.
            if "429" in str(exc):
                raise NewsFetchError("throttle", f"HTTP 429 for timespan={timespan}") from exc
            raise NewsFetchError("transport", f"{type(exc).__name__}: {exc}") from exc
        if result.status == 429:
            raise NewsFetchError("throttle", f"HTTP 429 for timespan={timespan}")
        if result.status != 200:
            raise NewsFetchError("http", f"HTTP {result.status} for timespan={timespan}")
        if not result.body.strip():
            # GDELT soft-throttles some clients with HTTP 200 + empty body
            # (BD-013, live evidence 2026-09-23): an empty artlist is never
            # valid JSON, and treating it as malformed would advance the
            # cursor past unsynced data.
            raise NewsFetchError("throttle", f"empty body (soft throttle) for timespan={timespan}")
        try:
            payload = json.loads(result.body)
        except json.JSONDecodeError as exc:
            raise NewsFetchError("malformed", f"body is not JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise NewsFetchError("malformed", "payload is not an object")
        articles = payload.get("articles", [])
        # Missing key and empty list are the same outcome (zero results).
        if articles is None:
            return []
        if not isinstance(articles, list) or any(not isinstance(a, dict) for a in articles):
            raise NewsFetchError("malformed", "articles is not a list of objects")
        return list(articles)


def ticker_token_of(canonical_symbol: str) -> str | None:
    """The standalone ticker token for a canonical symbol, if usable.

    Single-letter tickers never qualify as standalone evidence
    (collision guard in newsfilter); indices keep their mnemonic.

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    token = canonical_symbol.split(".", 1)[0]
    return token if len(token) >= 2 else None


def build_symbol_query(entry: SymbolEntry) -> str:
    """S0 query for one watchlist symbol (design §4).

    Implements: REQ-SI-FR-003, REQ-SI-FR-007 (ADR-002)
    """
    parts = [f'"{entry.official_name}"']
    parts += [f'"{alias}"' for alias in entry.aliases]
    token = ticker_token_of(entry.canonical_symbol)
    if token is not None:
        parts.append(token)
    return f"({' OR '.join(parts)}) sourcelang:english"


def build_macro_query(group: MacroGroup) -> str:
    """S0 query for one macro keyword group (design D4).

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    parts = [f'"{phrase}"' for phrase in group.phrases]
    return f"({' OR '.join(parts)}) sourcelang:english"


def watchlist_entries(conn: sqlite3.Connection) -> list[SymbolEntry]:
    """Active watchlist symbols joined to their evidence profile.

    Implements: REQ-SI-FR-007 (ADR-002)
    """
    rows = conn.execute(
        """
        SELECT s.canonical_symbol, s.official_name, s.aliases
        FROM watchlist w JOIN symbols s ON s.canonical_symbol = w.canonical_symbol
        WHERE w.status = 'active'
        ORDER BY s.canonical_symbol
        """
    ).fetchall()
    entries: list[SymbolEntry] = []
    for row in rows:
        try:
            aliases = tuple(json.loads(row["aliases"]))
        except (json.JSONDecodeError, TypeError):
            aliases = ()
        token = ticker_token_of(row["canonical_symbol"])
        entries.append(
            SymbolEntry(
                canonical_symbol=row["canonical_symbol"],
                official_name=row["official_name"],
                aliases=aliases,
                ticker_tokens=(token,) if token is not None else (),
            )
        )
    return entries


def _news_cursor(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT cursor FROM sync_state WHERE track = ?", (NEWS_TRACK,)).fetchone()
    return row["cursor"] if row else None


def _set_news_cursor(conn: sqlite3.Connection, value: str, now: datetime) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO sync_state (track, cursor, last_run_at, last_status, calls_today, calls_date)
            VALUES (?, ?, ?, 'ok', 0, NULL)
            ON CONFLICT(track) DO UPDATE SET
                cursor = excluded.cursor, last_run_at = excluded.last_run_at,
                last_status = excluded.last_status
            """,
            (NEWS_TRACK, value, _iso(now)),
        )


def _timespan_since(cursor: str | None, now: datetime) -> str:
    if cursor is None:
        return INITIAL_TIMESPAN
    try:
        last = datetime.fromisoformat(cursor)
    except ValueError:
        return INITIAL_TIMESPAN
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    days = max(1, (now - last).days)
    return f"{days}d"


def _rank_key(item: dict[str, Any]) -> tuple[float, str]:
    return (-float(item["source_tier"]), str(item["seendate"]))


def _store_batch(
    conn: sqlite3.Connection,
    bucket: str,
    query: str,
    raw_items: list[dict[str, Any]],
    entry: SymbolEntry | None,
    group: MacroGroup | None,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
) -> dict[str, int]:
    """Apply S1+S3+S4 to one fetched batch; one transaction (INV-003).

    Exactly one of ``entry`` / ``group`` is set: the query's evidence
    source. Gates run first (quarantine precedes scoring); kept rows go
    through both dedup keys with the deterministic survivor rule.
    """
    kept_new = dups = quarantined = 0
    dup_cutoff = _seendate_str(now - timedelta(days=DUP_WINDOW_DAYS))
    with conn:
        for raw in raw_items:
            item = {
                "title": raw.get("title"),
                "language": raw.get("language"),
                "seendate": raw.get("seendate"),
                "url": raw.get("url"),
                "domain": raw.get("domain"),
            }
            gate = structural_gates(
                item, window_start=window_start, window_end=window_end
            )
            if not gate.ok:
                assert gate.failure is not None
                failure: GateFailure = gate.failure
                conn.execute(
                    """
                    INSERT INTO news_quarantine
                        (bucket, url_norm, title, domain, published_at, fetched_at,
                         source_query, reason, failing_gate, detail)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bucket,
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
                quarantined += 1
                continue
            title = str(item["title"])
            domain = item.get("domain")
            if entry is not None:
                result = score_against_symbol(title, domain, entry)
            else:
                assert group is not None
                result = score_against_macro(title, domain, group)
            if not result.keep:
                continue
            url_norm = normalize_url(str(item["url"]))
            incoming = {
                "source_tier": result.source_tier,
                "seendate": item["seendate"],
                "title": item["title"],
                "url_raw": item["url"],
                "url_norm": url_norm,
            }
            # Key A: exact normalized URL within the bucket.
            row_a = conn.execute(
                "SELECT news_id, source_tier, published_at, title, url_raw, url_norm FROM news"
                " WHERE symbol = ? AND url_norm = ?",
                (bucket, url_norm),
            ).fetchone()
            if row_a is not None:
                stored = {k: row_a[k] for k in row_a.keys()}
                stored["seendate"] = stored.pop("published_at")
                if survivor_rank(incoming) < survivor_rank(stored):
                    conn.execute("DELETE FROM news WHERE news_id = ?", (stored["news_id"],))
                    _insert_article(conn, bucket, query, result, item, url_norm, now)
                dups += 1
                continue
            # Key B: title token-set similarity within the window.
            incoming_tokens = title_token_set(str(item["title"]))
            candidates = conn.execute(
                "SELECT news_id, source_tier, published_at, title, url_raw, url_norm FROM news"
                " WHERE symbol = ? AND published_at >= ?",
                (bucket, dup_cutoff),
            ).fetchall()
            duplicate = False
            for cand in candidates:
                cand_row = {k: cand[k] for k in cand.keys()}
                cand_row["seendate"] = cand_row.pop("published_at")
                if jaccard(incoming_tokens, title_token_set(cand_row["title"])) >= 0.8:
                    duplicate = True
                    if survivor_rank(incoming) < survivor_rank(cand_row):
                        conn.execute("DELETE FROM news WHERE news_id = ?", (cand_row["news_id"],))
                        _insert_article(conn, bucket, query, result, item, url_norm, now)
                    break
            if duplicate:
                dups += 1
                continue
            _insert_article(conn, bucket, query, result, item, url_norm, now)
            kept_new += 1
    return {"kept_new": kept_new, "dups": dups, "quarantined": quarantined}


def _insert_article(
    conn: sqlite3.Connection,
    bucket: str,
    query: str,
    result: "ScoreResultLike",
    item: dict[str, Any],
    url_norm: str,
    now: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO news
            (url_norm, title, domain, published_at, fetched_at, source_query,
             symbol, relevance_score, kept, url_raw, language, sourcecountry,
             score_breakdown, token_sources, source_tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
        """,
        (
            url_norm,
            item["title"],
            item.get("domain") or "",
            item["seendate"],
            _iso(now),
            query,
            bucket,
            result.score,
            item["url"],
            item.get("language") or "",
            item.get("sourcecountry"),
            json.dumps(
                {
                    "token_evidence": result.token_evidence,
                    "source_tier": result.source_tier,
                    "negative": result.negative,
                }
            ),
            json.dumps(list(result.token_sources)),
            result.source_tier,
        ),
    )


def run_news_sync(
    conn: sqlite3.Connection,
    adapter: GdeltNewsAdapter | None = None,
    *,
    now: datetime | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run the news track: queries -> filter -> store -> retention.

    Per-query failures are isolated; the first throttle aborts the
    remaining queries and leaves the cursor unadvanced so the next run
    re-covers the window. The report is the sole output surface.

    Implements: REQ-SI-FR-003, REQ-SI-FR-007, REQ-SI-INV-003 (ADR-002)
    """
    adapter = adapter if adapter is not None else GdeltNewsAdapter()
    now = now if now is not None else datetime.now(timezone.utc)
    cursor = _news_cursor(conn)
    timespan = _timespan_since(cursor, now)
    window_start = now - timedelta(days=RETENTION_DAYS)
    queries: list[tuple[str, str, SymbolEntry | None, MacroGroup | None]] = []
    for symbol_entry in watchlist_entries(conn):
        queries.append(
            (
                symbol_entry.canonical_symbol,
                build_symbol_query(symbol_entry),
                symbol_entry,
                None,
            )
        )
    for macro_group in MACRO_GROUPS:
        queries.append(
            (f"macro:{macro_group.name}", build_macro_query(macro_group), None, macro_group)
        )
    results: list[dict[str, Any]] = []
    aborted = False
    for index, (bucket, query, entry, group) in enumerate(queries):
        if index and sleep_fn is not None:
            sleep_fn(INTER_QUERY_SLEEP)
        try:
            raw_items = adapter.fetch(query, timespan)
        except NewsFetchError as exc:
            results.append({"query": query, "bucket": bucket, "status": exc.kind, "error": str(exc)})
            if exc.kind == "throttle":
                aborted = True
                for rest_bucket, rest_query, _rest_entry, _rest_group in queries[index + 1 :]:
                    results.append(
                        {"query": rest_query, "bucket": rest_bucket, "status": "aborted-throttle", "error": None}
                    )
                break
            continue
        counts = _store_batch(
            conn, bucket, query, raw_items, entry, group, window_start, now, now
        )
        results.append({"query": query, "bucket": bucket, "status": "ok", **counts})
    if not aborted:
        _set_news_cursor(conn, now.date().isoformat(), now)
    retention_cutoff = _iso(now - timedelta(days=RETENTION_DAYS))
    with conn:
        deleted_articles = conn.execute(
            "DELETE FROM news WHERE published_at < ?",
            (_seendate_str(now - timedelta(days=RETENTION_DAYS)),),
        ).rowcount
        deleted_quarantine = conn.execute(
            "DELETE FROM news_quarantine WHERE fetched_at < ?", (retention_cutoff,)
        ).rowcount
    return {
        "ran_at": _iso(now),
        "timespan": timespan,
        "queries": results,
        "cursor_advanced": not aborted,
        "retention_deleted": {"articles": deleted_articles or 0, "quarantine": deleted_quarantine or 0},
    }


def news_status(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read-only news-track status for sync.status.

    Implements: REQ-SI-FR-007 (ADR-002)
    """
    cursor = _news_cursor(conn)
    articles = conn.execute("SELECT COUNT(*) AS n FROM news").fetchone()["n"]
    quarantined = conn.execute("SELECT COUNT(*) AS n FROM news_quarantine").fetchone()["n"]
    buckets = conn.execute(
        "SELECT symbol, COUNT(*) AS n FROM news GROUP BY symbol ORDER BY symbol"
    ).fetchall()
    return {
        "cursor": cursor,
        "articles": articles,
        "quarantined": quarantined,
        "buckets": [{"bucket": row["symbol"], "articles": row["n"]} for row in buckets],
    }


__all__ = [
    "GDELT_BASE",
    "GdeltNewsAdapter",
    "INITIAL_TIMESPAN",
    "INTER_QUERY_SLEEP",
    "MACRO_GROUPS",
    "NEWS_TRACK",
    "NewsFetchError",
    "RETENTION_DAYS",
    "build_macro_query",
    "build_symbol_query",
    "news_status",
    "run_news_sync",
    "ticker_token_of",
    "watchlist_entries",
]
