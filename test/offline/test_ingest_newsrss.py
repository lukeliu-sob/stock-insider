"""Offline tests for the RSS listing track and the topical bucket (TP-035).

Fixture feeds in the three formats feedparser reads (RSS 2.0, Atom,
RDF), a fake page transport, no network (the offline conftest blocks
it). Pinned: the item mapping (dates, entities, tags, relevance domain
from the feed spec), S1-S5 reuse, the firehose prohibition for
symbol and macro buckets, topical admission and its cap, quarantine
visibility, cross-source dedup, the failure taxonomy, feed health,
and the parsers' bytes-only contract.

Implements: REQ-SI-FR-003, REQ-SI-FR-027, REQ-SI-INV-003, REQ-SI-SEC-003 (ADR-002)
"""

from __future__ import annotations

import socket
import sqlite3
from datetime import datetime, timezone

import pytest

from stockinsider.data.ingest import newsrss
from stockinsider.data.ingest.http import PageResult, TransportError
from stockinsider.data.ingest.newsrss import (
    TOPICAL_PER_FEED_RUN,
    FeedSpec,
    RssFeedAdapter,
    clean_text,
    run_rss_news_sync,
    store_feed_items,
)
from stockinsider.data.store.db import open_db
from stockinsider.data.store.vector import TOPICAL_BUCKET, ensure_vec_table, pending_news
from stockinsider.shared.egress import EgressViolationError

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
SPEC = FeedSpec("test:feed", "https://www.scmp.com/rss/91/feed", "scmp.com")
BBC = FeedSpec("bbc:business", "https://feeds.bbci.co.uk/news/business/rss.xml", "bbc.com")


def _store(tmp_path) -> sqlite3.Connection:
    conn = open_db(tmp_path / "rss.sqlite")
    with conn:
        conn.execute(
            "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type,"
            " aliases, verified, source, resolved_at)"
            " VALUES ('0700.HK', 'HK', 'Tencent Holdings', 'stock', '[\"Tencent\"]',"
            " 1, 'eodhd', '2026-09-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO watchlist (canonical_symbol, added_at, added_via) VALUES ('0700.HK', '2026-09-01', 'cli')"
        )
    return conn


def _rss(*items: tuple[str, str, str]) -> bytes:
    """(title, link, pubDate) triples -> an RSS 2.0 document."""
    body = "".join(
        f"<item><title>{title}</title><link>{link}</link><pubDate>{date}</pubDate>"
        f"<description>&lt;p&gt;Summary of {title}&lt;/p&gt;</description></item>"
        for title, link, date in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'.encode()


class _Pages:
    def __init__(self, pages: dict[str, PageResult | Exception]):
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url: str) -> PageResult:
        self.calls.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


def _ok(body: bytes, url: str = SPEC.url) -> PageResult:
    return PageResult(200, body, "application/rss+xml", url)


def _rows(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM news ORDER BY news_id").fetchall()


# -- parsing and mapping -----------------------------------------------------

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
<entry><title>Tencent Holdings &amp;amp; partners</title><link href="https://www.scmp.com/a1"/>
<updated>2026-10-25T08:30:00Z</updated><summary>Atom summary</summary></entry></feed>"""

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel rdf:about="https://www.scmp.com/"><title>t</title></channel>
<item rdf:about="https://www.scmp.com/a1"><title>Tencent Holdings &amp;amp; partners</title>
<link>https://www.scmp.com/a1</link><dc:date>2026-10-25T08:30:00Z</dc:date>
<description>RDF summary</description></item></rdf:RDF>"""


def test_rss_atom_and_rdf_map_to_the_same_fields() -> None:
    rss = _rss(("Tencent Holdings &amp;amp; partners", "https://www.scmp.com/a1", "Sat, 25 Oct 2026 08:30:00 GMT"))
    shapes = []
    for body in (rss, ATOM, RDF):
        (item,) = RssFeedAdapter(transport=_Pages({SPEC.url: _ok(body)})).fetch(SPEC)
        shapes.append((item["title"], item["url"], item["domain"], item["seendate"], item["language"]))
    assert len(set(shapes)) == 1
    assert shapes[0] == (
        "Tencent Holdings & partners",
        "https://www.scmp.com/a1",
        "scmp.com",
        "20261025T083000Z",
        "English",
    )


def test_rfc822_with_offset_normalizes_to_utc_seendate() -> None:
    body = _rss(("Tencent Holdings files results", "https://www.scmp.com/a2", "Sun, 26 Oct 2026 16:05:00 +0800"))
    (item,) = RssFeedAdapter(transport=_Pages({SPEC.url: _ok(body)})).fetch(SPEC)
    assert item["seendate"] == "20261026T080500Z"


def test_clean_text_unescapes_and_strips_tags() -> None:
    assert clean_text("<p>Rates &amp; <b>HIBOR</b>\n  ease</p>") == "Rates & HIBOR ease"
    assert clean_text(None) == ""


def test_relevance_domain_comes_from_the_feed_spec() -> None:
    body = _rss(("Markets wobble", "https://www.bbc.co.uk/news/articles/x1", "Sat, 25 Oct 2026 08:30:00 GMT"))
    (item,) = RssFeedAdapter(transport=_Pages({BBC.url: _ok(body, BBC.url)})).fetch(BBC)
    assert item["domain"] == "bbc.com"
    assert item["url"] == "https://www.bbc.co.uk/news/articles/x1"


# -- S1-S5 and the buckets ---------------------------------------------------


def _item(title: str, url: str, seendate: str = "20261025T083000Z", domain: str = "scmp.com") -> dict:
    return {"title": title, "url": url, "domain": domain, "seendate": seendate, "language": "English", "content": None}


def test_relevant_item_stores_in_symbol_bucket_with_rss_provenance(tmp_path) -> None:
    conn = _store(tmp_path)
    counts = store_feed_items(
        conn, SPEC, [_item("Tencent Holdings beats estimates", "https://www.scmp.com/t1")], now=NOW
    )
    assert counts["kept_new"] == 1 and counts["topical_new"] == 0
    (row,) = _rows(conn)
    assert (row["symbol"], row["source"], row["source_query"]) == ("0700.HK", "rss", "rss:test:feed")
    assert row["body_status"] == "not_applicable"


def test_unmatched_item_from_curated_feed_lands_in_topical(tmp_path) -> None:
    conn = _store(tmp_path)
    counts = store_feed_items(
        conn, SPEC, [_item("Typhoon signal raised over Hong Kong", "https://www.scmp.com/w1")], now=NOW
    )
    assert counts["topical_new"] == 1
    (row,) = _rows(conn)
    assert row["symbol"] == TOPICAL_BUCKET


def test_matched_item_is_never_duplicated_into_topical(tmp_path) -> None:
    conn = _store(tmp_path)
    store_feed_items(conn, SPEC, [_item("Tencent Holdings and the Fed rate path", "https://www.scmp.com/m1")], now=NOW)
    buckets = sorted(row["symbol"] for row in _rows(conn))
    assert buckets == ["0700.HK", "macro:fed"]


def test_non_topical_feed_keeps_the_firehose_prohibition(tmp_path) -> None:
    conn = _store(tmp_path)
    spec = FeedSpec("strict:feed", SPEC.url, "scmp.com", topical=False)
    counts = store_feed_items(conn, spec, [_item("Typhoon signal raised", "https://www.scmp.com/w2")], now=NOW)
    assert counts["rejected"] == 1
    assert _rows(conn) == []


def test_negative_signal_rejects_a_topical_item(tmp_path) -> None:
    conn = _store(tmp_path)
    counts = store_feed_items(
        conn, SPEC, [_item("Top stock picks for the weekend", "https://www.scmp.com/p1")], now=NOW
    )
    assert counts["rejected"] == 1 and counts["topical_new"] == 0


def test_topical_overflow_is_counted_not_stored(tmp_path) -> None:
    conn = _store(tmp_path)
    items = [
        _item(
            f"Weather story number {i} unrelated words {i * 7}", f"https://www.scmp.com/x{i}", f"20261025T08{i:02d}00Z"
        )
        for i in range(TOPICAL_PER_FEED_RUN + 3)
    ]
    counts = store_feed_items(conn, SPEC, items, now=NOW)
    assert counts["topical_new"] == TOPICAL_PER_FEED_RUN
    assert counts["topical_overflow"] == 3
    # newest first: the three oldest are the overflow
    stored = {row["url_raw"] for row in _rows(conn)}
    assert "https://www.scmp.com/x0" not in stored


def test_topical_rows_never_enter_the_embedding_backlog(tmp_path) -> None:
    conn = _store(tmp_path)
    store_feed_items(
        conn,
        SPEC,
        [
            _item("Typhoon signal raised", "https://www.scmp.com/w3"),
            _item("Tencent Holdings rally", "https://www.scmp.com/t3"),
        ],
        now=NOW,
    )
    titles = [title for _id, title in pending_news(conn)]
    assert titles == ["Tencent Holdings rally"]  # before the vector table exists
    ensure_vec_table(conn, "test-model", 3)
    titles = [title for _id, title in pending_news(conn)]
    assert titles == ["Tencent Holdings rally"]  # with the vector table (the production path)


def test_unparseable_date_and_stale_item_are_quarantined(tmp_path) -> None:
    conn = _store(tmp_path)
    counts = store_feed_items(
        conn,
        SPEC,
        [
            _item("Tencent Holdings undated", "https://www.scmp.com/u1", seendate=None),  # type: ignore[arg-type]
            _item("Tencent Holdings old news", "https://www.scmp.com/u2", seendate="20260901T000000Z"),
        ],
        now=NOW,
    )
    assert counts["quarantined"] == 2 and _rows(conn) == []
    gates = sorted(r["failing_gate"] for r in conn.execute("SELECT failing_gate FROM news_quarantine"))
    assert gates == ["seendate", "window"]
    assert {r["source"] for r in conn.execute("SELECT source FROM news_quarantine")} == {"rss"}


def test_key_a_duplicate_keeps_one_row_and_survivor_rule(tmp_path) -> None:
    conn = _store(tmp_path)
    first = _item("Tencent Holdings beats", "https://www.scmp.com/k1?utm_source=x", "20261025T100000Z")
    again = _item("Tencent Holdings beats estimates", "https://scmp.com/k1/", "20261025T090000Z")
    store_feed_items(conn, SPEC, [first], now=NOW)
    counts = store_feed_items(conn, SPEC, [again], now=NOW)
    assert counts["dups"] == 1
    (row,) = _rows(conn)
    assert row["published_at"] == "20261025T090000Z"  # same tier: the earlier seendate survives


def test_key_b_title_duplicate_of_a_gdelt_row_is_deduplicated(tmp_path) -> None:
    conn = _store(tmp_path)
    with conn:
        conn.execute(
            "INSERT INTO news (url_norm, url_raw, title, domain, published_at, fetched_at, source_query, symbol,"
            " relevance_score, kept, source_tier, source) VALUES ('reuters.com/a', 'https://reuters.com/a',"
            " 'Tencent Holdings beats estimates again', 'reuters.com', '20261025T070000Z', '2026-10-25', 'q',"
            " '0700.HK', 2.0, 1, 1.0, 'gdelt')"
        )
    counts = store_feed_items(
        conn, SPEC, [_item("Tencent Holdings beats estimates again", "https://www.scmp.com/k2")], now=NOW
    )
    assert counts["dups"] == 1
    assert [row["source"] for row in _rows(conn)] == ["gdelt"]


# -- failures, health, isolation ---------------------------------------------


def test_http_failure_is_classified_and_isolated(tmp_path) -> None:
    conn = _store(tmp_path)
    ok_spec = FeedSpec("ok:feed", "https://www.theguardian.com/uk/business/rss", "theguardian.com")
    pages = _Pages(
        {
            SPEC.url: TransportError("http-error", "HTTP 503 from x", status=503),
            ok_spec.url: _ok(
                _rss(("Tencent Holdings expands", "https://www.theguardian.com/a", "Sat, 25 Oct 2026 08:30:00 GMT")),
                ok_spec.url,
            ),
        }
    )
    report = run_rss_news_sync(
        conn, RssFeedAdapter(transport=pages), feeds=(SPEC, ok_spec), now=NOW, sleep_fn=lambda s: None
    )
    statuses = {row["feed"]: row["status"] for row in report["feeds"]}
    assert statuses == {"test:feed": "http", "ok:feed": "ok"}
    assert len(_rows(conn)) == 1


def test_malformed_feed_is_a_classified_failure(tmp_path) -> None:
    conn = _store(tmp_path)
    pages = _Pages({SPEC.url: _ok(b"<html><body>not a feed</body></html>")})
    report = run_rss_news_sync(conn, RssFeedAdapter(transport=pages), feeds=(SPEC,), now=NOW, sleep_fn=lambda s: None)
    assert report["feeds"][0]["status"] == "malformed"
    assert _rows(conn) == []


def test_consecutive_feed_failures_are_recorded(tmp_path) -> None:
    conn = _store(tmp_path)
    pages = _Pages({SPEC.url: TransportError("network", "down")})
    for _ in range(3):
        run_rss_news_sync(conn, RssFeedAdapter(transport=pages), feeds=(SPEC,), now=NOW, sleep_fn=lambda s: None)
    row = conn.execute("SELECT * FROM news_feed_health WHERE feed_id = ?", (SPEC.feed_id,)).fetchone()
    assert row["consecutive_failures"] == 3 and row["last_ok_at"] is None
    assert row["last_error"].startswith("transport")
    pages.pages[SPEC.url] = _ok(_rss(("Tencent Holdings", "https://www.scmp.com/h1", "Sat, 25 Oct 2026 08:30:00 GMT")))
    run_rss_news_sync(conn, RssFeedAdapter(transport=pages), feeds=(SPEC,), now=NOW, sleep_fn=lambda s: None)
    row = conn.execute("SELECT * FROM news_feed_health WHERE feed_id = ?", (SPEC.feed_id,)).fetchone()
    assert row["consecutive_failures"] == 0 and row["last_error"] is None


def test_pacing_follows_only_requests_that_reached_a_host(tmp_path) -> None:
    conn = _store(tmp_path)
    other = FeedSpec("other:feed", "https://www.theguardian.com/uk/business/rss", "theguardian.com")
    third = FeedSpec("third:feed", "https://hongkongfp.com/feed/", "hongkongfp.com")
    pages = _Pages(
        {
            SPEC.url: TransportError("network", "down"),
            other.url: TransportError("http-error", "HTTP 404", status=404),
            third.url: TransportError("network", "down"),
        }
    )
    sleeps: list[float] = []
    run_rss_news_sync(
        conn, RssFeedAdapter(transport=pages), feeds=(SPEC, other, third), now=NOW, sleep_fn=sleeps.append
    )
    assert sleeps == [newsrss.INTER_QUERY_SLEEP]  # only after the 404, which reached the host


def test_egress_denied_feed_fails_closed_with_zero_writes(tmp_path) -> None:
    conn = _store(tmp_path)
    evil = FeedSpec("evil:feed", "https://evil.example.com/rss", "scmp.com")
    report = run_rss_news_sync(conn, RssFeedAdapter(), feeds=(evil,), now=NOW, sleep_fn=lambda s: None)
    assert report["feeds"][0]["status"] == "egress"
    assert _rows(conn) == []
    assert conn.execute("SELECT COUNT(*) AS n FROM news_quarantine").fetchone()["n"] == 0


def test_redirect_off_the_whitelist_is_refused() -> None:
    from stockinsider.data.ingest.http import _EgressCheckedRedirects

    handler = _EgressCheckedRedirects()
    with pytest.raises(EgressViolationError):
        handler.redirect_request(None, None, 301, "Moved", {}, "https://evil.example.com/feed")
    with pytest.raises(EgressViolationError):
        handler.redirect_request(None, None, 301, "Moved", {}, "http://rthk9.rthk.hk/plain-http")


def test_parser_receives_bytes_and_opens_no_connection(tmp_path, monkeypatch) -> None:
    attempts: list[object] = []

    def refuse(self, address):  # type: ignore[no-untyped-def]
        attempts.append(address)
        raise OSError("blocked")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    body = _rss(("Tencent Holdings", "https://www.scmp.com/n1", "Sat, 25 Oct 2026 08:30:00 GMT"))
    items = RssFeedAdapter(transport=_Pages({SPEC.url: _ok(body)})).fetch(SPEC)
    assert len(items) == 1
    assert attempts == []


def test_unmatched_vendor_and_firehose_items_never_enter_topical(tmp_path) -> None:
    import json as _json

    from stockinsider.data.ingest.eodnews import EodhdNewsAdapter, run_eodhd_news_sync
    from stockinsider.data.ingest.http import FetchResult
    from stockinsider.data.ingest.news import GdeltNewsAdapter, run_news_sync

    conn = _store(tmp_path)
    unmatched_gdelt = {
        "title": "Typhoon signal raised over Hong Kong",
        "domain": "scmp.com",
        "seendate": "20261025T083000Z",
        "language": "English",
        "url": "https://www.scmp.com/w9",
    }
    unmatched_vendor = {
        "title": "Typhoon signal raised",
        "date": "2026-10-25T08:30:00+00:00",
        "link": "https://www.scmp.com/w8",
        "symbols": [],
        "content": "x",
    }
    gdelt = lambda url, params: FetchResult(200, _json.dumps({"articles": [unmatched_gdelt]}))  # noqa: E731
    vendor = lambda url, params: FetchResult(200, _json.dumps([unmatched_vendor]))  # noqa: E731
    run_news_sync(conn, GdeltNewsAdapter(transport=gdelt), now=NOW, sleep_fn=lambda s: None)
    run_eodhd_news_sync(conn, EodhdNewsAdapter(transport=vendor, api_key="k"), now=NOW)
    assert conn.execute("SELECT COUNT(*) AS n FROM news").fetchone()["n"] == 0
