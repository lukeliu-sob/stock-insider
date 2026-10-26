"""Body backfill track (TP-035): article bodies for whitelisted domains.

The D1 v2 body fetch (ADR-002 Am2, news-rss-body-design.md section 5),
the FR-015 whitelist + template mechanism applied at ingestion. Rows of
any source whose domain is on BODY_WHITELIST move from not_applicable
to pending; each run selects pending and failed rows published within
BODY_MAX_AGE_DAYS, evidence rows (symbol and macro buckets) before
topical rows and newest first within each, under fair-share caps;
older waiting rows are reported as stale. It fetches each distinct
article once through the
egress-checked page seam, and extracts the body with the domain's CSS
template (BeautifulSoup over the fetched bytes; the parser never opens
a connection). A body shorter than MIN_BODY_CHARS stores nothing
(FR-015b). Only failures that say something about the article count
toward MAX_ATTEMPTS (HTTP 4xx, extraction below the schema, a redirect
off the whitelist, an oversized page); transport errors, throttling and
HTTP 5xx are reported but never counted, so an outage cannot turn a
reachable article into a permanent `unavailable` row (INV-003). A
domain failing DOMAIN_PAUSE_AFTER times in a row is paused for the rest
of the run and its remaining rows are reported as paused. Bodies are
stored verbatim as crawled evidence; SEC-002 sanitization stays at the
egress boundary into model context.

Implements: REQ-SI-FR-015, REQ-SI-INV-003, REQ-SI-SEC-003 (ADR-002)
"""

from __future__ import annotations

import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from stockinsider.data.ingest import http as _http
from stockinsider.data.ingest.http import PageResult, PageTransport, TransportError
from stockinsider.data.ingest.news import _iso, _seendate_str
from stockinsider.data.store.vector import TOPICAL_BUCKET
from stockinsider.shared.egress import EgressViolationError

#: Body whitelist (design D5): candidates that passed the TP-035 live probe
#: (server-side fetchable, robots.txt allows the article paths), 2026-10-26.
BODY_WHITELIST: tuple[str, ...] = ("cnbc.com", "hongkongfp.com", "news.gov.hk", "rthk.hk")

#: Per-domain extraction templates (FR-015): CSS selectors whose matched
#: elements' text, in document order, is the body. Calibrated on the
#: version-controlled fixture pages; drift recalibrates, never degrades silently.
EXTRACTION_TEMPLATES: dict[str, tuple[str, ...]] = {
    "cnbc.com": ("div.ArticleBody-articleBody div.group > p",),
    "hongkongfp.com": ("div.entry-content > p",),
    "news.gov.hk": ("div.newsdetail-content p",),
    "rthk.hk": ("div.itemFullText",),
}

#: Extraction schema (FR-015b): a valid body has at least this many characters.
MIN_BODY_CHARS = 200

#: Counted attempts before a row becomes terminal `unavailable`.
MAX_ATTEMPTS = 3

#: Run caps (fair share): articles per run, articles per domain per run.
ARTICLES_PER_RUN = 30
ARTICLES_PER_DOMAIN = 10

#: Pacing between article fetches.
INTER_FETCH_SLEEP = 1.5

#: Consecutive failures that pause a domain for the rest of the run.
DOMAIN_PAUSE_AFTER = 5

#: Only articles published within this window are selected. Older rows
#: still waiting are reported as `stale` each run (visible, never fetched
#: late and never dropped silently); retention removes them in time.
BODY_MAX_AGE_DAYS = 14

_SKIPPED_TAGS = ("script", "style", "nav", "footer", "aside", "header", "noscript", "figure")
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")


def whitelist_domain(domain: object, url: object = None) -> str | None:
    """The BODY_WHITELIST entry covering a row's domain (or URL host), if any.

    Implements: REQ-SI-FR-015 (ADR-002)
    """
    hosts: list[str] = []
    if isinstance(domain, str) and domain:
        hosts.append(domain.lower().rstrip("."))
    if isinstance(url, str):
        host = urlparse(url).hostname
        if host:
            hosts.append(host.lower().rstrip("."))
    for host in hosts:
        for entry in BODY_WHITELIST:
            if host == entry or host.endswith("." + entry):
                return entry
    return None


def extract_body(domain: str, body: bytes) -> str:
    """Apply the domain's template; paragraphs joined by blank lines.

    Implements: REQ-SI-FR-015 (ADR-002)
    """
    selectors = EXTRACTION_TEMPLATES.get(domain)
    if not selectors:
        return ""
    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(list(_SKIPPED_TAGS)):
        tag.decompose()
    parts: list[str] = []
    for selector in selectors:
        for element in soup.select(selector):
            text = _WHITESPACE.sub(" ", element.get_text(" ", strip=True)).strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


class _Outcome:
    """One article's result: body text, or a failure with its counting rule."""

    def __init__(self, body: str | None = None, kind: str | None = None, counted: bool = False, detail: str = ""):
        self.body = body
        self.kind = kind
        self.counted = counted
        self.detail = detail


def fetch_article(url: str, domain: str, transport: PageTransport | None = None) -> _Outcome:
    """Fetch and extract one article; classify any failure.

    Implements: REQ-SI-FR-015, REQ-SI-INV-003, REQ-SI-SEC-003 (ADR-002)
    """
    try:
        page: PageResult = transport(url) if transport is not None else _http.stdlib_fetch_page(url)
    except EgressViolationError as exc:
        return _Outcome(kind="egress", counted=True, detail=str(exc))
    except TransportError as exc:
        if exc.kind == "too-large":
            return _Outcome(kind="too-large", counted=True, detail=str(exc))
        if exc.kind == "http-error" and exc.status is not None and 400 <= exc.status < 500 and exc.status != 429:
            return _Outcome(kind="http", counted=True, detail=str(exc))
        kind = "throttle" if exc.kind == "rate-limited" else ("http" if exc.kind == "http-error" else "transport")
        return _Outcome(kind=kind, counted=False, detail=str(exc))
    if page.status != 200:
        counted = 400 <= page.status < 500 and page.status != 429
        return _Outcome(kind="http", counted=counted, detail=f"HTTP {page.status}")
    text = extract_body(domain, page.body)
    if len(text) < MIN_BODY_CHARS:
        return _Outcome(kind="extraction", counted=True, detail=f"{len(text)} chars < {MIN_BODY_CHARS}")
    return _Outcome(body=text)


def promote_whitelisted(conn: sqlite3.Connection) -> int:
    """not_applicable -> pending for rows whose domain is on the whitelist.

    Implements: REQ-SI-FR-015 (ADR-002)
    """
    promoted = 0
    for entry in BODY_WHITELIST:
        promoted += conn.execute(
            """
            UPDATE news SET body_status = 'pending'
            WHERE body_status = 'not_applicable' AND (domain = ? OR domain LIKE ?)
            """,
            (entry, f"%.{entry}"),
        ).rowcount
    return promoted


def _work_queue(conn: sqlite3.Connection, cutoff: str) -> list[dict[str, Any]]:
    """Distinct articles awaiting a body (one fetch serves every bucket row).

    Evidence rows (symbol and macro buckets) come first, then topical
    rows; newest first within each. The run caps therefore spend on
    the bodies the analysis uses before the current-affairs context.
    """
    rows = conn.execute(
        """
        SELECT url_norm, MIN(url_raw) AS url, MIN(domain) AS domain, MAX(published_at) AS published_at,
               MIN(CASE WHEN symbol = ? THEN 1 ELSE 0 END) AS topical_only
        FROM news
        WHERE body_status IN ('pending', 'failed') AND published_at >= ?
        GROUP BY url_norm
        ORDER BY topical_only ASC, published_at DESC
        """,
        (TOPICAL_BUCKET, cutoff),
    ).fetchall()
    return [dict(row) for row in rows]


def run_body_backfill(
    conn: sqlite3.Connection,
    transport: PageTransport | None = None,
    *,
    now: datetime | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    progress: "Callable[[str], None] | None" = None,
) -> dict[str, Any]:
    """Run the body track once; the report is the sole output surface.

    Implements: REQ-SI-FR-015, REQ-SI-INV-003 (ADR-002)
    """
    now = now if now is not None else datetime.now(timezone.utc)
    cutoff = _seendate_str(now - timedelta(days=BODY_MAX_AGE_DAYS))
    with conn:
        promoted = promote_whitelisted(conn)
    stale = conn.execute(
        "SELECT COUNT(DISTINCT url_norm) AS n FROM news WHERE body_status IN ('pending', 'failed') AND published_at < ?",
        (cutoff,),
    ).fetchone()["n"]
    counts = {"extracted": 0, "failed": 0, "unavailable": 0, "uncounted": 0, "paused": 0, "deferred": 0}
    failures: list[dict[str, str]] = []
    per_domain: dict[str, int] = {}
    streak: dict[str, int] = {}
    paused: set[str] = set()
    fetched = 0
    reached_host = False
    for article in _work_queue(conn, cutoff):
        domain = whitelist_domain(article["domain"], article["url"])
        if domain is None:
            continue  # whitelist shrank since promotion: never fetched (FR-015a)
        if domain in paused:
            counts["paused"] += 1
            continue
        if fetched >= ARTICLES_PER_RUN or per_domain.get(domain, 0) >= ARTICLES_PER_DOMAIN:
            counts["deferred"] += 1
            continue
        if reached_host and sleep_fn is not None:
            sleep_fn(INTER_FETCH_SLEEP)  # pacing follows requests that reached a host
        fetched += 1
        per_domain[domain] = per_domain.get(domain, 0) + 1
        outcome = fetch_article(article["url"], domain, transport)
        reached_host = outcome.kind not in ("transport", "egress")
        with conn:
            if outcome.body is not None:
                conn.execute(
                    """
                    UPDATE news SET body = ?, body_status = 'extracted', body_fetched_at = ?
                    WHERE url_norm = ? AND body_status IN ('pending', 'failed')
                    """,
                    (outcome.body, _iso(now), article["url_norm"]),
                )
                counts["extracted"] += 1
                streak[domain] = 0
                continue
            streak[domain] = streak.get(domain, 0) + 1
            failures.append({"url": article["url"], "kind": str(outcome.kind), "detail": outcome.detail})
            if outcome.counted:
                conn.execute(
                    """
                    UPDATE news SET body_attempts = body_attempts + 1,
                        body_status = CASE WHEN body_attempts + 1 >= ? THEN 'unavailable' ELSE 'failed' END
                    WHERE url_norm = ? AND body_status IN ('pending', 'failed')
                    """,
                    (MAX_ATTEMPTS, article["url_norm"]),
                )
                terminal = conn.execute(
                    "SELECT COUNT(*) AS n FROM news WHERE url_norm = ? AND body_status = 'unavailable'",
                    (article["url_norm"],),
                ).fetchone()["n"]
                counts["unavailable" if terminal else "failed"] += 1
            else:
                counts["uncounted"] += 1
        if streak[domain] >= DOMAIN_PAUSE_AFTER:
            paused.add(domain)
            if progress is not None:
                progress(f"news/body {domain}: paused after {DOMAIN_PAUSE_AFTER} consecutive failures")
    if progress is not None:
        progress(
            f"news/body: extracted={counts['extracted']} failed={counts['failed']} "
            f"unavailable={counts['unavailable']} paused={counts['paused']} deferred={counts['deferred']} "
            f"stale={stale}"
        )
    return {
        "ran_at": _iso(now),
        "promoted": promoted,
        **counts,
        "stale": stale,
        "paused_domains": sorted(paused),
        "failures": failures,
    }


def body_status(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read-only body status: rows per state, including title-only rows.

    Implements: REQ-SI-FR-015, REQ-SI-INV-003 (ADR-002)
    """
    rows = conn.execute("SELECT body_status, COUNT(*) AS n FROM news GROUP BY body_status").fetchall()
    return {"by_status": {row["body_status"]: row["n"] for row in rows}}
