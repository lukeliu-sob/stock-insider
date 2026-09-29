"""TP-015 P0: CLI rendering, progress emission, help grouping, prompt.

Implements: REQ-SI-FR-013, REQ-SI-FR-001, REQ-SI-FR-005 (ADR-001, ADR-002)
"""

from __future__ import annotations

import io
from typing import Any

from typer.testing import CliRunner

from stockinsider.cli.app import app
from stockinsider.cli.render import (
    chrome,
    day_change_styled,
    info_lines_chromed,
    news_track_lines,
    sync_notable_lines,
    sync_summary_line,
    sync_verbose_lines,
)


def test_chrome_degrades_typography() -> None:
    assert chrome("a\u2014b\u00b7c\u2192d") == "a-b|c->d"
    assert all(ord(ch) < 128 for ch in chrome("\u2014\u2013\u00b7\u2018\u2019\u201c\u201d\u2192\u25b2\u25bc"))


def test_sync_summary_compact_and_failures_visible() -> None:
    report: dict[str, Any] = {
        "ran_at": "2026-09-27T00:00:00+00:00",
        "counts": {"ok": 3, "failed": 1, "deferred": 12},
        "calls": {"used": 18, "cap": 100000, "remaining": 99982},
        "results": [
            {"status": "ok", "symbol": "0700.HK", "action": "incremental", "detail": "5 rows"},
            {"status": "deferred", "symbol": "9988.HK", "action": "backfill", "detail": "budget"},
            {"status": "failed", "symbol": "1211.HK", "action": "gap-repair", "detail": "HTTP 500"},
        ],
        "news": {
            "gdelt": {"failed": "gdelt track aborted: throttled"},
            "eodhd": {
                "ran_at": "2026-09-27T00:00:00+00:00",
                "queries": [
                    {"bucket": "0700.HK", "status": "ok", "kept_new": 49, "dups": 1, "quarantined": 0},
                    {"bucket": "1211.HK", "status": "ok", "kept_new": 49, "dups": 1, "quarantined": 0},
                    {"bucket": "9988.HK", "status": "ok", "kept_new": 50, "dups": 0, "quarantined": 0},
                ],
                "cursor_advanced": True,
            },
        },
    }
    summary = sync_summary_line(report)
    assert "ok 3" in summary and "deferred 12" in summary and "99982" in summary
    notable = sync_notable_lines(report)
    assert len(notable) == 1 and "1211.HK" in notable[0] and "HTTP 500" in notable[0]
    verbose = sync_verbose_lines(report)
    assert len(verbose) == 3
    assert any("deferred" in line and "budget" in line for line in verbose)
    news = news_track_lines(report)
    assert any("news/gdelt FAILED" in line for line in news)
    assert any("new 148 | dup 2" in line for line in news)
    assert any("cursor advanced" in line for line in news)


def test_info_lines_chromed_ascii() -> None:
    out = info_lines_chromed(["0700.HK \u2014 Tencent Holdings (HKEX)"])
    assert out == ["0700.HK - Tencent Holdings (HKEX)"]
    assert all(ord(ch) < 128 for ch in out[0])


def test_day_change_region_colors() -> None:
    up = "day change (2026-09-26 vs 2026-09-25): +1.23%"
    down = "day change (2026-09-26 vs 2026-09-25): -0.40%"
    # HK: red up / green down
    assert day_change_styled("0700.HK", up).startswith("\033[31m")
    assert day_change_styled("0700.HK", down).startswith("\033[32m")
    # US: green up / red down
    assert day_change_styled("AAPL.US", up).startswith("\033[32m")
    assert day_change_styled("AAPL.US", down).startswith("\033[31m")
    # zero and non-move lines untouched
    zero = "day change (2026-09-26 vs 2026-09-25): +0.00%"
    assert day_change_styled("0700.HK", zero) == zero
    other = "quote (2026-09-26): close 549"
    assert day_change_styled("0700.HK", other) == other


def test_help_grouped_and_hides_unimplemented(monkeypatch) -> None:
    from stockinsider.agent import repl as repl_mod

    out: list[str] = []
    repl_mod._cmd_help(out.append)
    text = "\n".join(out)
    assert "session" in text and "data" in text and "tools" in text
    assert "/sessions" in text and "/watch" in text and "/exit" in text
    assert "/compact" not in text and "/config" not in text


def test_context_prompt_plain_when_not_tty(monkeypatch, tmp_path) -> None:
    from stockinsider.agent import repl as repl_mod

    class _FakeWatch:
        def list(self):
            return []

    class _FakeStore:
        watchlist = _FakeWatch()

        def sync_status(self):
            return {"calls": {"remaining": 99982}}

    monkeypatch.setattr("sys.stdin", io.StringIO())  # not a tty
    assert repl_mod._context_prompt(_FakeStore()) == "stockinsider> "


def test_sync_command_streams_progress_and_summary(
    monkeypatch, tmp_path
) -> None:
    """CLI sync: progress lines + compact tail (no per-item spam)."""
    from stockinsider.cli import app as app_mod

    class _FakeStore:
        def __init__(self, conn):
            self._conn = conn

        def run_sync(self, progress=None):
            if progress is not None:
                progress("plan: 1 market item(s)")
                progress("market 0700.HK incremental: ok (5 rows) +0.1s")
            return {
                "ran_at": "2026-09-27T00:00:00+00:00",
                "counts": {"ok": 1, "failed": 0, "deferred": 0},
                "calls": {"used": 1, "cap": 100000, "remaining": 99999},
                "results": [
                    {"status": "ok", "symbol": "0700.HK", "action": "incremental", "detail": "5 rows"}
                ],
            }

        def close(self):
            pass

    monkeypatch.setattr(app_mod, "open_data_store", lambda root=None: _FakeStore(None))
    runner = CliRunner()
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0, result.output
    assert "plan: 1 market item" in result.output
    assert "market 0700.HK incremental: ok" in result.output
    assert "ok 1 | failed 0 | deferred 0" in result.output
    assert "wall time" in result.output


def test_sync_verbose_shows_every_item(monkeypatch) -> None:
    from stockinsider.cli import app as app_mod

    class _FakeStore:
        def run_sync(self, progress=None):
            return {
                "ran_at": "2026-09-27T00:00:00+00:00",
                "counts": {"ok": 1, "failed": 0, "deferred": 1},
                "calls": {"used": 2, "cap": 100000, "remaining": 99998},
                "results": [
                    {"status": "ok", "symbol": "0700.HK", "action": "incremental", "detail": "5 rows"},
                    {"status": "deferred", "symbol": "9988.HK", "action": "backfill", "detail": "budget"},
                ],
            }

        def close(self):
            pass

    monkeypatch.setattr(app_mod, "open_data_store", lambda root=None: _FakeStore())
    runner = CliRunner()
    result = runner.invoke(app, ["sync", "--verbose"])
    assert result.exit_code == 0, result.output
    assert "deferred 9988.HK" in result.output
    # default run hides deferred detail
    result2 = runner.invoke(app, ["sync"])
    assert "9988.HK" not in result2.output


def test_sync_service_emits_progress_sequence(tmp_path) -> None:
    """The data-side emission order: plan, per-item, track boundaries."""
    from stockinsider.data.ingest.sync import SyncService
    from stockinsider.data.store.db import open_db

    conn = open_db(tmp_path / "prog.sqlite")
    service = SyncService(conn, transport=None)
    # budget disabled market fetch without transport? force plan-empty path:
    lines: list[str] = []
    report = service.run(progress=lines.append)
    assert isinstance(report.as_dict()["counts"]["ok"], int)
    # with no watchlist rows and seeded benchmarks already? plan may be non-empty;
    # assert the boundaries exist in order regardless
    if any(item.startswith("market") for item in lines):
        assert lines[0].startswith("plan:")
    assert lines[-1].startswith("sync tracks complete")
