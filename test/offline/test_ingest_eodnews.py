"""Offline tests for the EODHD news source (TP-014).

Fixture payloads mirror the 2026-09-27 live probe (content,
structured sentiment, multi-market symbols, tags). The vendor
entity hit as evidence, verbatim storage, cross-source dedup, the
error taxonomy, and quarantine gating are pinned.

Implements: REQ-SI-FR-003, REQ-SI-FR-007, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from stockinsider.data.ingest.eodnews import (
    EodhdNewsAdapter,
    map_item,
    run_eodhd_news_sync,
)
from stockinsider.data.ingest.http import FetchResult
from stockinsider.data.store.db import open_db


def _store(tmp_path) -> sqlite3.Connection:
    return open_db(tmp_path / "eod.sqlite")


def _seed_watchlist(conn) -> None:
    with conn:
        conn.execute(
            "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type,"
            " aliases, verified, source, resolved_at)"
            " VALUES ('0700.HK', 'HKEX', 'Tencent Holdings', 'stock', '[\"Tencent\"]',"
            " 1, 'eodhd', '2026-09-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO watchlist (canonical_symbol, added_at, added_via) VALUES ('0700.HK', '2026-09-01', 'cli')"
        )


def _vendor_item(
    title="Tencent Cloud PalmAI Unveils Palm X",
    *,
    symbols=None,
    date="2026-09-25T18:33:00+00:00",
    link="https://www.example.com/palm-x",
    content="Body text of the story.",
) -> dict:
    return {
        "title": title,
        "content": content,
        "date": date,
        "link": link,
        "sentiment": {"polarity": 0.998, "neg": 0.02, "neu": 0.862, "pos": 0.118},
        "symbols": symbols if symbols is not None else ["0700.HK", "NNN1.F"],
        "tags": ["Technology", "AI"],
    }


class _Stub:
    def __init__(self, items_by_symbol=None, *, status=200, body="[]"):
        self.calls: list[dict] = []
        self.items = items_by_symbol or {}
        self.status = status
        self.body = body

    def __call__(self, url, params):
        self.calls.append(dict(params))
        if self.status != 200:
            return FetchResult(self.status, self.body)
        return FetchResult(200, json.dumps(self.items.get(params.get("s"), [])))


def _run(conn, stub, *, now=None):
    now = now or datetime(2026, 9, 27, tzinfo=timezone.utc)
    return run_eodhd_news_sync(conn, EodhdNewsAdapter(transport=stub, api_key="test"), now=now)


def test_fetch_parses_live_shape(tmp_path) -> None:
    conn = _store(tmp_path)
    _seed_watchlist(conn)
    stub = _Stub({"0700.HK": [_vendor_item()]})

    report = _run(conn, stub)

    assert stub.calls[0]["s"] == "0700.HK" and stub.calls[0]["fmt"] == "json"
    ok = next(q for q in report["queries"] if q["bucket"] == "0700.HK")
    assert ok["status"] == "ok" and ok["kept_new"] == 1
    row = conn.execute("SELECT title, content, sentiment, source, published_at FROM news").fetchone()
    assert row["title"].startswith("Tencent Cloud")
    assert row["content"] == "Body text of the story."
    assert json.loads(row["sentiment"])["polarity"] == 0.998
    assert row["source"] == "eodhd"
    assert row["published_at"] == "20260925T183300Z"  # ISO -> sortable form


def test_symbols_hit_is_evidence(tmp_path) -> None:
    conn = _store(tmp_path)
    _seed_watchlist(conn)
    # title carries neither ticker nor name — only the symbols list does
    item = _vendor_item(title="Palm X takes on rivals in cloud AI", symbols=["0700.HK"])
    report = _run(conn, _Stub({"0700.HK": [item]}))
    ok = next(q for q in report["queries"])
    assert ok["kept_new"] == 1
    row = conn.execute("SELECT relevance_score FROM news").fetchone()
    assert row["relevance_score"] >= 1.0  # entity evidence alone keeps


def test_name_fallback_and_rejection(tmp_path) -> None:
    conn = _store(tmp_path)
    _seed_watchlist(conn)
    items = {
        "0700.HK": [
            _vendor_item(
                title="Tencent Holdings buys back shares",
                symbols=[],
                link="https://www.example.com/name-only",
            ),
            _vendor_item(
                title="Unrelated fintech roundup",
                symbols=[],
                link="https://www.example.com/other",
            ),
        ]
    }
    report = _run(conn, _Stub(items))
    ok = next(q for q in report["queries"])
    assert ok["kept_new"] == 1  # official-name phrase keeps
    assert ok["rejected"] == 1  # no evidence at all -> rejected, not stored


def test_cross_source_dedup(tmp_path) -> None:
    conn = _store(tmp_path)
    _seed_watchlist(conn)
    # GDELT stored the same article earlier (same normalized URL)
    with conn:
        conn.execute(
            "INSERT INTO news (url_norm, url_raw, title, domain, published_at, fetched_at,"
            " source_query, symbol, relevance_score, kept, source)"
            " VALUES ('example.com/palm-x', 'https://example.com/palm-x',"
            " 'Tencent Cloud PalmAI Unveils Palm X', 'example.com', '20260925T183300Z',"
            " '2026-09-25T00:00:00+00:00', 'gdelt', '0700.HK', 1.5, 1, 'gdelt')"
        )
    report = _run(conn, _Stub({"0700.HK": [_vendor_item()]}))
    ok = next(q for q in report["queries"])
    assert ok["kept_new"] == 0 and ok["dups"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM news").fetchone()["c"] == 1


def test_error_taxonomy_and_isolation(tmp_path) -> None:
    conn = _store(tmp_path)
    _seed_watchlist(conn)
    for status, kind in ((401, "auth"), (402, "http"), (429, "throttle"), (500, "http")):
        stub = _Stub(status=status, body='"err"')
        report = _run(conn, stub)
        entry = next(q for q in report["queries"])
        assert entry["status"] == kind, (status, entry)


def test_quarantine_window_gates(tmp_path) -> None:
    conn = _store(tmp_path)
    _seed_watchlist(conn)
    stale = _vendor_item(date="2023-01-01T00:00:00+00:00")
    report = _run(conn, _Stub({"0700.HK": [stale]}))
    ok = next(q for q in report["queries"])
    assert ok["quarantined"] == 1 and ok["kept_new"] == 0
    row = conn.execute("SELECT failing_gate, source FROM news_quarantine").fetchone()
    assert row["failing_gate"] == "window" and row["source"] == "eodhd"


def test_budget_deferred(tmp_path) -> None:
    conn = _store(tmp_path)
    _seed_watchlist(conn)

    class _NoBudget:
        def try_spend(self, units: int) -> bool:
            return False

    report = run_eodhd_news_sync(
        conn,
        EodhdNewsAdapter(transport=_Stub(), api_key="k"),
        now=datetime(2026, 9, 27, tzinfo=timezone.utc),
        budget=_NoBudget(),
    )
    assert report["queries"][0]["status"] == "deferred"
    assert report["calls_spent"] == 0


def test_map_item_shapes_gates() -> None:
    item = map_item(_vendor_item(link="https://www.scmp.com/tech/palm-x"))
    assert item["domain"] == "www.scmp.com"
    assert item["language"] == "English"
    assert item["seendate"] == "20260925T183300Z"
    assert item["symbols"] == ["0700.HK", "NNN1.F"]
