"""Offline tests for TP-035 storage, lookup, egress and sync integration.

Pinned: migration v7 -> v8 on an existing store (old rows become
title-only `not_applicable`, nothing else moves), the refuse-newer
rule, the lookup paths answered by indexes (EXPLAIN QUERY PLAN), the
news fetch hosts as their own egress set, and per-track isolation of
the RSS and body tracks inside a sync run.

Implements: REQ-SI-FR-003, REQ-SI-FR-015, REQ-SI-FR-027, REQ-SI-INV-003, REQ-SI-SEC-003 (ADR-002, ADR-003)
"""

from __future__ import annotations

import sqlite3

import pytest

from stockinsider.data.ingest.http import FetchResult
from stockinsider.data.store.db import DB_FILENAME, SCHEMA_VERSION, SchemaVersionError, open_db
from stockinsider.data.store.schema import MIGRATIONS
from stockinsider.shared.egress import (
    EGRESS_WHITELIST,
    NEWS_FETCH_HOSTS,
    EgressViolationError,
    validate_egress_url,
)


def _v7_store(root) -> None:
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / DB_FILENAME)
    conn.execute("CREATE TABLE schema_history (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for index, ddl in enumerate(MIGRATIONS[:7], start=1):
        conn.executescript(ddl)
        conn.execute("INSERT INTO schema_history VALUES (?, '2026-10-01T00:00:00+00:00')", (index,))
    conn.execute(
        "INSERT INTO news (url_norm, url_raw, title, domain, published_at, fetched_at, source_query, symbol,"
        " relevance_score, kept, source) VALUES ('cnbc.com/a', 'https://www.cnbc.com/a', 'Old row', 'cnbc.com',"
        " '20261001T000000Z', '2026-10-01', 'q', '0700.HK', 2.0, 1, 'gdelt')"
    )
    conn.commit()
    conn.close()


def test_v7_store_migrates_to_v8_and_old_rows_are_title_only(tmp_path) -> None:
    root = tmp_path / "data"
    _v7_store(root)
    conn = open_db(root)
    assert SCHEMA_VERSION == 8
    assert conn.execute("SELECT MAX(version) FROM schema_history").fetchone()[0] == 8
    row = conn.execute("SELECT title, body, body_status, body_attempts, body_fetched_at FROM news").fetchone()
    assert dict(row) == {
        "title": "Old row",
        "body": None,
        "body_status": "not_applicable",
        "body_attempts": 0,
        "body_fetched_at": None,
    }
    assert conn.execute("SELECT COUNT(*) FROM news_feed_health").fetchone()[0] == 0


def test_a_v9_store_is_refused(tmp_path) -> None:
    root = tmp_path / "data"
    conn = open_db(root)
    with conn:
        conn.execute("INSERT INTO schema_history (version, applied_at) VALUES (9, '2049-01-01T00:00:00+00:00')")
    conn.close()
    with pytest.raises(SchemaVersionError, match="newer than this code"):
        open_db(root)


@pytest.mark.parametrize(
    ("sql", "params", "index"),
    [
        ("SELECT url_norm FROM news WHERE body_status IN ('pending', 'failed')", (), "idx_news_body_queue"),
        ("UPDATE news SET body = 'x' WHERE url_norm = ?", ("a",), "idx_news_url_norm"),
        ("DELETE FROM news WHERE published_at < ?", ("20240101T000000Z",), "idx_news_published"),
        ("SELECT source, COUNT(*) FROM news GROUP BY source", (), "idx_news_source"),
        ("DELETE FROM news_quarantine WHERE fetched_at < ?", ("2024-01-01",), "idx_news_quarantine_fetched"),
        (
            "SELECT news_id FROM news WHERE symbol = ? AND published_at >= ?",
            ("topical", "2026"),
            "idx_news_bucket_seen",
        ),
    ],
)
def test_hot_lookups_are_index_backed(tmp_path, sql, params, index) -> None:
    conn = open_db(tmp_path / "data")
    plan = " ".join(str(row[3]) for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", params))
    assert index in plan, plan


def test_news_hosts_are_their_own_egress_set() -> None:
    assert NEWS_FETCH_HOSTS.isdisjoint(EGRESS_WHITELIST)
    for url in (
        "https://www.scmp.com/rss/91/feed",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "https://rthk9.rthk.hk/rthk/news/rss/e_expressnews_efinance.xml",
        "https://www.news.gov.hk/en/common/html/topstories.rss.xml",
    ):
        validate_egress_url(url)
    for refused in ("https://www.marketwatch.com/rss", "https://www.chinadailyhk.com/", "http://rthk9.rthk.hk/x.xml"):
        with pytest.raises(EgressViolationError):
            validate_egress_url(refused)


def test_rss_and_body_tracks_are_isolated_inside_a_sync(tmp_path, monkeypatch) -> None:
    from stockinsider.data.ingest import newsrss
    from stockinsider.data.ingest.sync import SyncService

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("rss exploded")

    monkeypatch.setattr(newsrss, "run_rss_news_sync", boom)
    conn = open_db(tmp_path / "data")
    report = SyncService(conn, transport=lambda url, params: FetchResult(429, "{}")).run()
    assert report.news is not None
    assert report.news["rss"] == {"failed": "rss track aborted: rss exploded"}
    assert "queries" in report.news["gdelt"] and "eodhd" in report.news
    assert report.news["body"]["extracted"] == 0 and "failed" in report.news["body"]


def test_sync_status_reports_feed_health_and_body_states(tmp_path) -> None:
    from stockinsider.data.ingest.sync import sync_status

    conn = open_db(tmp_path / "data")
    with conn:
        conn.execute("INSERT INTO news_feed_health (feed_id, consecutive_failures) VALUES ('scmp:top', 2)")
    status = sync_status(conn)
    assert status["news_rss"]["feeds"][0]["consecutive_failures"] == 2
    assert status["news_rss"]["topical_articles"] == 0
    assert status["news_body"] == {"by_status": {}}


# -- visibility of the new tracks (INV-003) ---------------------------------


def _report(rss, body) -> dict:
    return {"news": {"rss": rss, "body": body}}


def test_run_summary_renders_rss_and_body_tracks() -> None:
    from stockinsider.cli.render import news_track_lines

    rss = {
        "ran_at": "2026-10-26T04:35:00+00:00",
        "feeds": [
            {
                "feed": "scmp:top",
                "status": "ok",
                "kept_new": 1,
                "topical_new": 30,
                "dups": 0,
                "quarantined": 0,
                "topical_overflow": 4,
            },
            {"feed": "rthk:finance", "status": "transport", "error": "transport: network down"},
        ],
    }
    body = {
        "ran_at": "2026-10-26T04:36:00+00:00",
        "extracted": 27,
        "failed": 3,
        "unavailable": 0,
        "uncounted": 1,
        "paused": 2,
        "deferred": 98,
        "stale": 5,
        "paused_domains": ["hongkongfp.com"],
        "failures": [
            {"kind": "extraction", "url": "u", "detail": "d"},
            {"kind": "transport", "url": "u", "detail": "d"},
        ],
    }
    lines = news_track_lines(_report(rss, body))
    text = "\n".join(lines)
    assert "news/rss 2026-10-26T04:35:00+00:00: 1/2 feeds ok | new 1 | topical 30" in text
    assert "topical overflow 4" in text
    assert "rthk:finance" in text and "transport: network down" in text
    assert "news/body 2026-10-26T04:36:00+00:00: extracted 27 | failed 3" in text and "stale 5" in text
    assert "domains: hongkongfp.com" in text
    assert "failures extraction=1 transport=1" in text


def test_run_summary_reports_aborted_tracks_explicitly() -> None:
    from stockinsider.cli.render import news_track_lines

    lines = news_track_lines(_report({"failed": "rss track aborted: boom"}, {"failed": "body track aborted: boom"}))
    assert lines == ["news/rss FAILED: rss track aborted: boom", "news/body FAILED: body track aborted: boom"]


def test_repl_sync_status_shows_feed_health_and_body_states(tmp_path) -> None:
    from stockinsider.agent.registry import Registry, register_sync_tools
    from stockinsider.agent.repl import _cmd_sync
    from stockinsider.data import open_data_store

    ds = open_data_store(str(tmp_path / "data"))
    with ds.conn:
        ds.conn.execute("INSERT INTO news_feed_health VALUES ('scmp:top', 0, '2026-10-26T04:00:00+00:00', NULL)")
        ds.conn.execute("INSERT INTO news_feed_health VALUES ('rthk:local', 3, NULL, 'transport: down')")
        for status, url in (("extracted", "a"), ("pending", "b"), ("not_applicable", "c")):
            ds.conn.execute(
                "INSERT INTO news (url_norm, url_raw, title, domain, published_at, fetched_at, source_query, symbol,"
                " relevance_score, kept, body_status) VALUES (?, ?, 't', 'cnbc.com', '20261025T000000Z', 'x', 'q',"
                " 'topical', 0.0, 1, ?)",
                (url, url, status),
            )
    registry = Registry()
    register_sync_tools(registry, ds)
    lines: list[str] = []
    _cmd_sync(registry, ["status"], lines.append)
    text = "\n".join(lines)
    assert "news feeds: 1 healthy, 1 failing; topical articles: 3" in text
    assert "feed: rthk:local failing 3 run(s) in a row (last ok never; transport: down)" in text
    assert "article bodies: extracted=1 pending=1 title-only=1" in text
