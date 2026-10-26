"""RSS listing track (TP-035): curated feeds into the five-stage pipeline.

A third S0 listing source next to GDELT and EODHD (ADR-002 Am2,
news-rss-body-design.md section 4). Feeds are fetched through the
egress-checked page seam (bytes, fixed User-Agent, every redirect hop
re-validated) and parsed by feedparser from those bytes only, so the
parser never opens a connection of its own. Each entry is normalized
to the pipeline's item shape (title and summary unescaped and
tag-stripped, publication time in the sortable seendate form, the
relevance domain taken from the feed spec), then runs the unchanged
S1/S2 evaluation against every active watchlist symbol and macro
group. For symbol and macro buckets the firehose prohibition holds:
an item is stored only where token evidence fired. Items from a
curated feed that match no bucket go to the topical bucket
(REQ-SI-FR-027): negative signals still reject, and at most
TOPICAL_PER_FEED_RUN new rows per feed per run are stored, the
overflow counted. Dedup is the shared Key A / Key B with the
deterministic survivor rule, so it works across sources. Per-feed
failures are classified, isolated and recorded in news_feed_health.

Implements: REQ-SI-FR-003, REQ-SI-FR-027, REQ-SI-INV-003, REQ-SI-SEC-003 (ADR-002)
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import feedparser
from bs4 import BeautifulSoup

from stockinsider.data.ingest import http as _http
from stockinsider.data.ingest.http import PageResult, PageTransport, TransportError
from stockinsider.data.ingest.news import (
    DUP_WINDOW_DAYS,
    INTER_QUERY_SLEEP,
    MACRO_GROUPS,
    _iso,
    _seendate_str,
    watchlist_entries,
)
from stockinsider.data.ingest.newsfilter import (
    ScoreResult,
    evaluate_item,
    jaccard,
    negative_signals,
    normalize_title,
    normalize_url,
    source_tier,
    survivor_rank,
    title_token_set,
)
from stockinsider.data.store.vector import TOPICAL_BUCKET
from stockinsider.shared.egress import EgressViolationError

#: sync_state track key for the RSS cursor (informational; dedup is the idempotence).
RSS_TRACK = "news:rss"

#: S1 window for feed items: the cursor is informational, so a fixed lookback (D6).
RSS_LOOKBACK_DAYS = 14

#: New topical rows stored per feed per run, newest first; overflow is counted.
TOPICAL_PER_FEED_RUN = 30

#: Feed items carry no language field; the curated feeds are English (config-of-record).
FEED_LANGUAGE = "English"


@dataclass(frozen=True)
class FeedSpec:
    """One curated feed: id, URL, relevance domain, topical flag.

    `domain` is the S2 relevance domain (on a tier list); the URL's host
    is the fetch host the egress gate checks, and the two may differ.

    Implements: REQ-SI-FR-003, REQ-SI-FR-027 (ADR-002)
    """

    feed_id: str
    url: str
    domain: str
    topical: bool = True


#: Config-of-record (design D6; URLs fixed by the TP-035 live probe, 2026-10-26).
RSS_FEEDS: tuple[FeedSpec, ...] = (
    FeedSpec("scmp:top", "https://www.scmp.com/rss/91/feed", "scmp.com"),
    FeedSpec("scmp:china", "https://www.scmp.com/rss/4/feed", "scmp.com"),
    FeedSpec("bbc:business", "https://feeds.bbci.co.uk/news/business/rss.xml", "bbc.com"),
    FeedSpec("guardian:business", "https://www.theguardian.com/uk/business/rss", "theguardian.com"),
    FeedSpec("cnbc:top", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "cnbc.com"),
    FeedSpec("rthk:finance", "https://rthk9.rthk.hk/rthk/news/rss/e_expressnews_efinance.xml", "rthk.hk"),
    FeedSpec("rthk:local", "https://rthk9.rthk.hk/rthk/news/rss/e_expressnews_elocal.xml", "rthk.hk"),
    FeedSpec("hkfp:all", "https://hongkongfp.com/feed/", "hongkongfp.com"),
    FeedSpec("govhk:finance", "https://www.news.gov.hk/en/categories/finance/html/articlelist.rss.xml", "news.gov.hk"),
    FeedSpec("govhk:top", "https://www.news.gov.hk/en/common/html/topstories.rss.xml", "news.gov.hk"),
)


class RssFetchError(RuntimeError):
    """A classified feed failure.

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind  # "http" | "throttle" | "transport" | "egress" | "malformed"
        self.detail = detail


_WHITESPACE = re.compile(r"\s+")


def clean_text(raw: object) -> str:
    """Entities unescaped, tags stripped, whitespace collapsed (deterministic).

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    if not isinstance(raw, str):
        return ""
    text = BeautifulSoup(raw, "html.parser").get_text(" ")
    return _WHITESPACE.sub(" ", html.unescape(text)).strip()


def _entry_seendate(entry: Any) -> str | None:
    """feedparser's parsed UTC time (RFC 822 or ISO 8601) -> seendate; None if absent."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is None:
        return None
    try:
        return time.strftime("%Y%m%dT%H%M%SZ", parsed)
    except (TypeError, ValueError):
        return None


def map_entry(spec: FeedSpec, entry: Any) -> dict[str, Any]:
    """One feed entry -> the pipeline's item shape.

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    link = entry.get("link")
    return {
        "title": clean_text(entry.get("title")) or None,
        "url": link if isinstance(link, str) else None,
        "domain": spec.domain,
        "seendate": _entry_seendate(entry),
        "language": FEED_LANGUAGE,
        "content": clean_text(entry.get("summary")) or None,
    }


class RssFeedAdapter:
    """Fetch and parse one curated feed through the page seam.

    Implements: REQ-SI-FR-003, REQ-SI-INV-003, REQ-SI-SEC-003 (ADR-002)
    """

    def __init__(self, transport: PageTransport | None = None) -> None:
        self._transport = transport

    def _fetch(self, url: str) -> PageResult:
        if self._transport is not None:
            return self._transport(url)
        return _http.stdlib_fetch_page(url)

    def fetch(self, spec: FeedSpec) -> list[dict[str, Any]]:
        """Return the feed's items mapped to the pipeline shape.

        Implements: REQ-SI-FR-003, REQ-SI-INV-003 (ADR-002)
        """
        try:
            page = self._fetch(spec.url)
        except EgressViolationError as exc:
            raise RssFetchError("egress", str(exc)) from exc
        except TransportError as exc:
            if exc.kind == "rate-limited":
                raise RssFetchError("throttle", str(exc)) from exc
            if exc.kind == "http-error":
                raise RssFetchError("http", str(exc)) from exc
            raise RssFetchError("transport", str(exc)) from exc
        if page.status == 429:
            raise RssFetchError("throttle", f"HTTP 429 for {spec.feed_id}")
        if page.status != 200:
            raise RssFetchError("http", f"HTTP {page.status} for {spec.feed_id}")
        parsed = feedparser.parse(page.body)
        if not parsed.entries:
            reason = f"bozo: {parsed.get('bozo_exception')}" if parsed.bozo else "no entries"
            raise RssFetchError("malformed", f"{spec.feed_id}: no usable items ({reason})")
        return [map_entry(spec, entry) for entry in parsed.entries]


def _set_feed_health(conn: sqlite3.Connection, feed_id: str, now: datetime, error: str | None) -> None:
    if error is None:
        conn.execute(
            """
            INSERT INTO news_feed_health (feed_id, consecutive_failures, last_ok_at, last_error)
            VALUES (?, 0, ?, NULL)
            ON CONFLICT(feed_id) DO UPDATE SET
                consecutive_failures = 0, last_ok_at = excluded.last_ok_at, last_error = NULL
            """,
            (feed_id, _iso(now)),
        )
    else:
        conn.execute(
            """
            INSERT INTO news_feed_health (feed_id, consecutive_failures, last_ok_at, last_error)
            VALUES (?, 1, NULL, ?)
            ON CONFLICT(feed_id) DO UPDATE SET
                consecutive_failures = consecutive_failures + 1, last_error = excluded.last_error
            """,
            (feed_id, error),
        )


def _set_rss_cursor(conn: sqlite3.Connection, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO sync_state (track, cursor, last_run_at, last_status, calls_today, calls_date)
        VALUES (?, ?, ?, 'ok', 0, NULL)
        ON CONFLICT(track) DO UPDATE SET
            cursor = excluded.cursor, last_run_at = excluded.last_run_at, last_status = excluded.last_status
        """,
        (RSS_TRACK, now.date().isoformat(), _iso(now)),
    )


def topical_score(item: dict[str, Any]) -> ScoreResult:
    """The topical bucket's verdict: no token floor, negative signals reject.

    Implements: REQ-SI-FR-027 (ADR-002)
    """
    title = str(item["title"])
    domain = item.get("domain")
    tier = source_tier(domain)
    negative = negative_signals(normalize_title(title), domain)
    return ScoreResult(
        bucket=TOPICAL_BUCKET,
        token_evidence=0.0,
        token_sources=(),
        source_tier=tier,
        negative=negative,
        score=tier + negative,
        keep=negative == 0.0,
    )


def _insert(
    conn: sqlite3.Connection,
    bucket: str,
    query: str,
    item: dict[str, Any],
    url_norm: str,
    score: ScoreResult,
    now: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO news
            (url_norm, url_raw, title, domain, published_at, fetched_at, source_query,
             symbol, relevance_score, kept, language, score_breakdown, token_sources,
             source_tier, content, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 'rss')
        """,
        (
            url_norm,
            item["url"],
            item["title"],
            item["domain"],
            item["seendate"],
            _iso(now),
            query,
            bucket,
            score.score,
            item["language"],
            json.dumps(
                {"token_evidence": score.token_evidence, "source_tier": score.source_tier, "negative": score.negative}
            ),
            json.dumps(list(score.token_sources)),
            score.source_tier,
            item.get("content"),
        ),
    )


def _store(
    conn: sqlite3.Connection,
    bucket: str,
    query: str,
    item: dict[str, Any],
    score: ScoreResult,
    now: datetime,
) -> bool:
    """S3 + S4 for one bucket: True when a new row was stored, False for a duplicate."""
    url_norm = normalize_url(str(item["url"]))
    incoming = {"source_tier": score.source_tier, "seendate": item["seendate"]}
    row_a = conn.execute(
        "SELECT news_id, source_tier, published_at FROM news WHERE symbol = ? AND url_norm = ?",
        (bucket, url_norm),
    ).fetchone()
    if row_a is not None:
        if survivor_rank(incoming) < survivor_rank(
            {"source_tier": row_a["source_tier"], "seendate": row_a["published_at"]}
        ):
            conn.execute("DELETE FROM news WHERE news_id = ?", (row_a["news_id"],))
            _insert(conn, bucket, query, item, url_norm, score, now)
        return False
    cutoff = _seendate_str(now - timedelta(days=DUP_WINDOW_DAYS))
    tokens = title_token_set(str(item["title"]))
    for cand in conn.execute(
        "SELECT news_id, source_tier, published_at, title FROM news WHERE symbol = ? AND published_at >= ?",
        (bucket, cutoff),
    ).fetchall():
        if jaccard(tokens, title_token_set(cand["title"])) >= 0.8:
            if survivor_rank(incoming) < survivor_rank(
                {"source_tier": cand["source_tier"], "seendate": cand["published_at"]}
            ):
                conn.execute("DELETE FROM news WHERE news_id = ?", (cand["news_id"],))
                _insert(conn, bucket, query, item, url_norm, score, now)
            return False
    _insert(conn, bucket, query, item, url_norm, score, now)
    return True


def _quarantine(conn: sqlite3.Connection, spec: FeedSpec, item: dict[str, Any], failure: Any, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO news_quarantine
            (bucket, url_norm, title, domain, published_at, fetched_at,
             source_query, reason, failing_gate, detail, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rss')
        """,
        (
            f"rss:{spec.feed_id}",
            item["url"] if isinstance(item["url"], str) else "",
            item["title"] if isinstance(item["title"], str) else "",
            item["domain"],
            item["seendate"] if isinstance(item["seendate"], str) else "",
            _iso(now),
            f"rss:{spec.feed_id}",
            failure.gate,
            failure.gate,
            failure.detail,
        ),
    )


def store_feed_items(
    conn: sqlite3.Connection,
    spec: FeedSpec,
    items: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, int]:
    """S1-S4 for one fetched feed; one transaction (INV-003).

    Implements: REQ-SI-FR-003, REQ-SI-FR-027, REQ-SI-INV-003 (ADR-002)
    """
    counts = {
        "kept_new": 0,
        "topical_new": 0,
        "dups": 0,
        "quarantined": 0,
        "rejected": 0,
        "topical_overflow": 0,
    }
    symbols = watchlist_entries(conn)
    window_start = now - timedelta(days=RSS_LOOKBACK_DAYS)
    query = f"rss:{spec.feed_id}"
    # newest first, so the topical cap keeps the freshest items; undated items last (they quarantine)
    ordered = sorted(items, key=lambda item: item["seendate"] or "", reverse=True)
    with conn:
        for item in ordered:
            verdict = evaluate_item(
                item, symbols=symbols, macro_groups=MACRO_GROUPS, window_start=window_start, window_end=now
            )
            if verdict.quarantined is not None:
                _quarantine(conn, spec, item, verdict.quarantined, now)
                counts["quarantined"] += 1
                continue
            kept = [score for score in verdict.bucket_scores if score.keep]
            if kept:
                for score in kept:
                    counts["kept_new" if _store(conn, score.bucket, query, item, score, now) else "dups"] += 1
                continue
            if not spec.topical:
                counts["rejected"] += 1
                continue
            score = topical_score(item)
            if not score.keep:
                counts["rejected"] += 1
                continue
            if counts["topical_new"] >= TOPICAL_PER_FEED_RUN:
                counts["topical_overflow"] += 1
                continue
            counts["topical_new" if _store(conn, TOPICAL_BUCKET, query, item, score, now) else "dups"] += 1
    return counts


def run_rss_news_sync(
    conn: sqlite3.Connection,
    adapter: RssFeedAdapter | None = None,
    *,
    feeds: tuple[FeedSpec, ...] = RSS_FEEDS,
    now: datetime | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    progress: "Callable[[str], None] | None" = None,
) -> dict[str, Any]:
    """Run the RSS track over every curated feed; the report is the output.

    Feeds are paced by INTER_QUERY_SLEEP after every request that reached
    a host; a fetch that failed before reaching one (transport, egress)
    is not followed by a pause. One feed failing never stops the others.

    Implements: REQ-SI-FR-003, REQ-SI-FR-027, REQ-SI-INV-003 (ADR-002)
    """
    adapter = adapter if adapter is not None else RssFeedAdapter()
    now = now if now is not None else datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    reached_host = False
    for spec in feeds:
        if reached_host and sleep_fn is not None:
            sleep_fn(INTER_QUERY_SLEEP)
        try:
            items = adapter.fetch(spec)
        except RssFetchError as exc:
            reached_host = exc.kind in ("http", "throttle", "malformed")
            with conn:
                _set_feed_health(conn, spec.feed_id, now, f"{exc.kind}: {exc.detail}")
            results.append({"feed": spec.feed_id, "status": exc.kind, "error": str(exc)})
            if progress is not None:
                progress(f"news/rss {spec.feed_id}: {exc.kind}")
            continue
        reached_host = True
        counts = store_feed_items(conn, spec, items, now=now)
        with conn:
            _set_feed_health(conn, spec.feed_id, now, None)
        results.append({"feed": spec.feed_id, "status": "ok", **counts})
        if progress is not None:
            progress(
                f"news/rss {spec.feed_id}: ok new={counts['kept_new']} topical={counts['topical_new']} "
                f"dup={counts['dups']} quarantined={counts['quarantined']}"
            )
    with conn:
        _set_rss_cursor(conn, now)
    return {"ran_at": _iso(now), "source": "rss", "feeds": results}


def rss_news_status(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read-only RSS status: per-feed health and the topical bucket size.

    Implements: REQ-SI-FR-027, REQ-SI-INV-003 (ADR-002)
    """
    health = conn.execute(
        "SELECT feed_id, consecutive_failures, last_ok_at, last_error FROM news_feed_health ORDER BY feed_id"
    ).fetchall()
    topical = conn.execute("SELECT COUNT(*) AS n FROM news WHERE symbol = ?", (TOPICAL_BUCKET,)).fetchone()["n"]
    return {"feeds": [dict(row) for row in health], "topical_articles": topical}
