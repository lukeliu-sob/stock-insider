"""Offline tests for the GDELT news pipeline (TP-011b: transport, storage).

Covers: S0 query construction and pacing, the fetch failure taxonomy
(429/HTTP/malformed), storage with both dedup keys and quarantine
visibility, macro buckets, throttle abort with cursor hold, cursor
resume windows, two-year retention via the structural window, track
isolation inside the market sync, and the status surface.

Implements: REQ-SI-FR-003, REQ-SI-FR-007, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from stockinsider.data.ingest.http import FetchResult
from stockinsider.data.ingest.news import (
    INTER_QUERY_SLEEP,
    INITIAL_TIMESPAN,
    MACRO_GROUPS,
    GdeltNewsAdapter,
    NewsFetchError,
    build_macro_query,
    build_symbol_query,
    news_status,
    run_news_sync,
)
from stockinsider.data.ingest.newsfilter import MacroGroup, SymbolEntry
from stockinsider.data.store.db import open_db

SYMBOL_QUERY_0700 = '("Tencent Holdings" OR "Tencent" OR 0700) sourcelang:english'


def _news_store(tmp_path) -> sqlite3.Connection:
    return open_db(tmp_path / "news.sqlite")


def _seed_symbol(conn, canonical="0700.HK", name="Tencent Holdings") -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type,
                                 aliases, verified, source, resolved_at)
            VALUES (?, 'HKEX', ?, 'stock', '["Tencent"]', 1, 'eodhd',
                    '2026-09-01T00:00:00+00:00')
            """,
            (canonical, name),
        )
        conn.execute(
            "INSERT INTO watchlist (canonical_symbol, added_at, added_via) VALUES (?, '2026-09-01', 'cli')",
            (canonical,),
        )


def _article(title, domain="reuters.com", seendate="20260918T090000Z", url=None, **extra):
    item = {
        "title": title,
        "domain": domain,
        "seendate": seendate,
        "language": "English",
        "url": url or f"https://www.{domain}/a/{abs(hash(title)) % 99999}",
        "sourcecountry": "United States",
    }
    item.update(extra)
    return item


class _GdeltStub:
    """Transport stub returning canned artlist payloads per query."""

    def __init__(self, items_by_query=None):
        self.calls: list[dict] = []
        self.items_by_query = items_by_query or {}

    def __call__(self, url, params):
        self.calls.append(dict(params))
        items = self.items_by_query.get(params["query"], [])
        payload = json.dumps({"articles": items})
        return FetchResult(200, payload)


# ---- S0: query construction ---------------------------------------------------


def test_query_construction() -> None:
    entry = SymbolEntry("0700.HK", "Tencent Holdings", ("Tencent",), ("0700",))
    assert build_symbol_query(entry) == SYMBOL_QUERY_0700
    group = MacroGroup("fed", ("federal reserve",))
    assert build_macro_query(group) == '("federal reserve") sourcelang:english'


def test_run_queries_watchlist_plus_macros_with_pacing(tmp_path) -> None:
    conn = _news_store(tmp_path)
    _seed_symbol(conn)
    stub = _GdeltStub()
    sleeps: list[float] = []

    report = run_news_sync(conn, GdeltNewsAdapter(transport=stub), sleep_fn=sleeps.append)

    assert len(stub.calls) == 7  # 1 symbol + 6 macro groups
    assert stub.calls[0]["query"] == SYMBOL_QUERY_0700
    assert stub.calls[0]["mode"] == "artlist" and stub.calls[0]["format"] == "json"
    assert stub.calls[0]["maxrecs"] == "75"
    assert sleeps == [INTER_QUERY_SLEEP] * 6
    assert report["cursor_advanced"] is True
    assert all(q["status"] == "ok" for q in report["queries"])


# ---- failure taxonomy ----------------------------------------------------------


def test_fetch_failure_taxonomy() -> None:
    cases = [
        (429, "{}", "throttle"),
        (500, "oops", "http"),
        (200, "not-json", "malformed"),
        (200, '"a string"', "malformed"),
        (200, '{"articles": "nope"}', "malformed"),
    ]
    for status, body, kind in cases:
        adapter = GdeltNewsAdapter(transport=lambda url, params, _s=status, _b=body: FetchResult(_s, _b))
        with pytest.raises(NewsFetchError) as exc:
            adapter.fetch("x", "1d")
        assert exc.value.kind == kind, (status, body)


def test_empty_result_missing_key_and_list_identical() -> None:
    adapter = GdeltNewsAdapter(transport=lambda url, params: FetchResult(200, "{}"))
    assert adapter.fetch("x", "1d") == []
    adapter2 = GdeltNewsAdapter(transport=lambda url, params: FetchResult(200, '{"articles": []}'))
    assert adapter2.fetch("x", "1d") == []


# ---- S4: storage, dedup, quarantine -------------------------------------------


def test_store_filter_dedup_and_quarantine(tmp_path) -> None:
    conn = _news_store(tmp_path)
    _seed_symbol(conn)
    keep = _article("0700 wins approval for two mobile game titles")
    key_a = _article("Tencent Holdings buys back shares", url="https://www.reuters.com/deal")
    key_a_variant = dict(key_a, url="https://m.reuters.com/deal/?utm_source=feed")
    key_b = _article(
        "Tencent Holdings buys back shares now",
        url="https://www.reuters.com/deal2",
    )
    promo = _article("Top stock picks: buy 0700 now", domain="pennysheet.example")
    non_english = _article("Tencent results beat", language="Chinese")
    stub = _GdeltStub({SYMBOL_QUERY_0700: [keep, key_a, key_a_variant, key_b, promo, non_english]})

    report = run_news_sync(conn, GdeltNewsAdapter(transport=stub), sleep_fn=lambda s: None)

    symbol_query = next(q for q in report["queries"] if q["bucket"] == "0700.HK")
    assert symbol_query["status"] == "ok"
    assert symbol_query["kept_new"] == 2  # keep + key_a (official-phrase evidence)
    assert symbol_query["dups"] == 2  # key A variant + key B near-title
    assert symbol_query["quarantined"] == 1  # language gate
    rows = conn.execute("SELECT title FROM news ORDER BY title").fetchall()
    assert [r["title"] for r in rows] == [
        "0700 wins approval for two mobile game titles",
        "Tencent Holdings buys back shares",
    ]
    gates = [r["failing_gate"] for r in conn.execute("SELECT failing_gate FROM news_quarantine")]
    assert gates == ["language"]


def test_dedup_survivor_prefers_tier(tmp_path) -> None:
    conn = _news_store(tmp_path)
    _seed_symbol(conn)
    # same url_norm: general tier first, tier-A arrives later and replaces
    general = _article(
        "Tencent Holdings AGM minutes posted",
        domain="cnn.com",
        url="https://edition.cnn.com/agm",
    )
    tier_a = _article(
        "Tencent Holdings AGM minutes posted",
        domain="scmp.com",
        url="https://www.scmp.com/agm",
    )
    # craft identical normalized URLs
    general["url"] = "https://www.reuters.com/agm"
    tier_a["url"] = "http://reuters.com/agm/"
    stub = _GdeltStub({SYMBOL_QUERY_0700: [general]})
    run_news_sync(conn, GdeltNewsAdapter(transport=stub), sleep_fn=lambda s: None)
    stub2 = _GdeltStub({SYMBOL_QUERY_0700: [tier_a]})
    report = run_news_sync(conn, GdeltNewsAdapter(transport=stub2), sleep_fn=lambda s: None)
    symbol_query = next(q for q in report["queries"] if q["bucket"] == "0700.HK")
    assert symbol_query["dups"] == 1
    row = conn.execute("SELECT domain, source_tier FROM news").fetchone()
    assert row["domain"] == "scmp.com" and row["source_tier"] == 1.0


def test_macro_bucket_storage(tmp_path) -> None:
    conn = _news_store(tmp_path)
    _seed_symbol(conn)
    fed = _article("Federal Reserve holds rates steady, signals patience")
    stub = _GdeltStub({build_macro_query(MACRO_GROUPS[0]): [fed]})

    report = run_news_sync(conn, GdeltNewsAdapter(transport=stub), sleep_fn=lambda s: None)

    fed_query = next(q for q in report["queries"] if q["bucket"] == "macro:fed")
    assert fed_query["kept_new"] == 1
    rows = conn.execute("SELECT symbol AS bucket FROM news").fetchall()
    assert [r["bucket"] for r in rows] == ["macro:fed"]


# ---- throttle and cursor --------------------------------------------------------


def test_throttle_aborts_and_cursor_holds(tmp_path) -> None:
    conn = _news_store(tmp_path)
    _seed_symbol(conn)
    stub = _GdeltStub()

    def throttling(url, params):
        stub.calls.append(dict(params))
        return FetchResult(429, "{}")

    report = run_news_sync(conn, GdeltNewsAdapter(transport=throttling), sleep_fn=lambda s: None)

    assert report["queries"][0]["status"] == "throttle"
    assert all(q["status"] == "aborted-throttle" for q in report["queries"][1:])
    assert len(stub.calls) == 1  # no hammering after the 429
    assert report["cursor_advanced"] is False
    assert conn.execute("SELECT cursor FROM sync_state WHERE track = 'news'").fetchone() is None


def test_cursor_resume_window(tmp_path) -> None:
    conn = _news_store(tmp_path)
    _seed_symbol(conn)
    stub = _GdeltStub()
    day1 = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

    run_news_sync(conn, GdeltNewsAdapter(transport=stub), now=day1, sleep_fn=lambda s: None)
    assert stub.calls[0]["timespan"] == INITIAL_TIMESPAN

    day3 = day1 + timedelta(days=3)
    stub.calls.clear()
    run_news_sync(conn, GdeltNewsAdapter(transport=stub), now=day3, sleep_fn=lambda s: None)
    assert stub.calls[0]["timespan"] == "3d"


# ---- S5: retention (via the structural window) ---------------------------------


def test_retention_two_year(tmp_path) -> None:
    conn = _news_store(tmp_path)
    _seed_symbol(conn)
    old = _article("Tencent Holdings posts results", seendate="20230601T090000Z")
    fresh = _article("Tencent Holdings wins new approval", seendate="20260918T090000Z")
    stub = _GdeltStub({SYMBOL_QUERY_0700: [old, fresh]})
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)

    run_news_sync(conn, GdeltNewsAdapter(transport=stub), now=now, sleep_fn=lambda s: None)

    kept = conn.execute("SELECT title FROM news").fetchall()
    assert [r["title"] for r in kept] == ["Tencent Holdings wins new approval"]
    gates = [r["failing_gate"] for r in conn.execute("SELECT failing_gate FROM news_quarantine")]
    assert "window" in gates


# ---- track isolation and status --------------------------------------------------


def test_track_isolation_inside_market_sync(tmp_path) -> None:
    from stockinsider.data.ingest.sync import SyncService

    conn = _news_store(tmp_path)
    # empty watchlist: market plan is empty; news always fires (macro groups)
    service = SyncService(conn, transport=lambda url, params: FetchResult(429, "{}"))
    report = service.run()
    assert report.news is not None
    assert report.news["queries"][0]["status"] == "throttle"
    assert isinstance(report.results, list)  # market report intact


def test_news_status_surface(tmp_path) -> None:
    conn = _news_store(tmp_path)
    _seed_symbol(conn)
    item = _article(
        "Tencent Holdings files quarterly results",
        domain="hkexnews.hk",
        url="https://www.hkexnews.hk/x.pdf",
    )
    stub = _GdeltStub({SYMBOL_QUERY_0700: [item]})

    run_news_sync(conn, GdeltNewsAdapter(transport=stub), sleep_fn=lambda s: None)

    status = news_status(conn)
    assert status["articles"] == 1
    assert status["buckets"] == [{"bucket": "0700.HK", "articles": 1}]
    assert status["cursor"] is not None
