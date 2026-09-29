"""TP-017 PR-3a: numbers pipeline (ledger, structural tokens, M7/M11, N1/N4/N5).

Implements: REQ-SI-INV-001, REQ-SI-FR-006, REQ-SI-FR-007
"""

from __future__ import annotations

import io

from stockinsider.agent.guardrail import postcheck_numbers

POOL = {
    "market.quote#1": {"symbol": "0700.HK", "close": 436.6, "adjusted_close": 436.6},
    "market.quote#2": {"symbol": "1211.HK", "close": 77.7},
}


def test_heading_ordinals_are_layout() -> None:
    text = "## 6. Known gaps\n## 7. Caveats\nvalue 436.6 stands"
    check = postcheck_numbers(text, POOL)
    assert check.passed, check.failed


def test_symbol_fragments_are_structural() -> None:
    check = postcheck_numbers("comparing 0700 with 1211 on close 436.6", POOL)
    assert check.passed, check.failed


def test_absent_symbol_fragment_still_fails() -> None:
    check = postcheck_numbers("code 9988 mentioned alongside 436.6", POOL)
    assert not check.passed
    assert "9988" in check.failed or "9988" in [t.lstrip("-") for t in check.failed]


def test_fabrication_still_fails_with_structural_present() -> None:
    check = postcheck_numbers("0700 closed at 436.7", POOL)
    assert not check.passed


def test_cross_turn_ledger_restatement_passes(tmp_path) -> None:
    """Turn 2 restating a turn-1 number is a citation of session evidence."""
    from stockinsider.agent.loop import TurnEngine
    from stockinsider.agent.providers import ChatOutcome
    from stockinsider.agent.registry import Registry
    from stockinsider.agent.session import SessionStore

    class Provider:
        def __init__(self):
            self.messages = []

        def complete(self, messages, *, tools=None, stream_sink=None):
            self.messages.append(list(messages))
            if len(self.messages) == 1:
                return ChatOutcome(text="the close was 436.6", usage={})
            return ChatOutcome(text="as I said, the close was 436.6", usage={})

    store = SessionStore(root=tmp_path / "s")

    class FakeStore(SessionStore):
        pass

    # seed a prior snapshot as if turn 1 carried the quote
    record = store.create(profile="quick")
    store.snapshot(record["session_id"], "turn-0000", {"market.quote#1": POOL["market.quote#1"]})

    engine = TurnEngine(store, Registry(), Provider())
    outcome = engine.run_turn(
        record["session_id"],
        "what was that close again?",
        profile="quick",
        render=lambda s: None,
        progress=lambda s: None,
    )
    assert not outcome.quarantined, outcome.displayed
    assert "436.6" in outcome.displayed


def test_news_recent_k_is_bounded(tmp_path) -> None:
    """M11: k is clamped to [1, 25]; k=-1 cannot return the whole table."""

    from stockinsider.agent.registry import Registry, register_news_tools
    from stockinsider.data.store.db import open_db
    from stockinsider.shared.tools import ToolCall

    conn = open_db(tmp_path / "n.sqlite")

    class DS:
        def __init__(self, c):
            self.conn = c

        def news_recent_rows(self, symbol, k):
            assert 1 <= k <= 25, k  # the clamp must hold at the facade seam
            return [
                {"title": "t", "url_raw": "u", "domain": "d", "published_at": "p", "source": "eodhd", "sentiment": None}
            ][:k]

    registry = Registry()
    register_news_tools(registry, DS(conn))
    for raw in (-1, 0, 99):
        result = registry.execute(
            ToolCall(tool="news.recent", arguments={"symbol": "0700.HK", "k": raw}, call_id=f"k{raw}")
        )
        assert result.ok, result.error


def test_indicators_use_adjusted_prices(tmp_path) -> None:
    """M7: risk metrics price the adjusted series, not raw closes."""
    from stockinsider.data.store.db import open_db

    conn = open_db(tmp_path / "m7.sqlite")
    rows = []
    for i in range(30):
        date = f"2026-07-{i + 1:02d}"
        raw = 100.0 if i < 15 else 200.0  # a 100% raw jump mid-series
        adjusted = 100.0  # vanishes on the adjusted series (split)
        rows.append((date, raw, adjusted))
    with conn:
        conn.execute(
            "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type,"
            " aliases, verified, source, resolved_at) VALUES ('X.HK','HK','X','stock',"
            " '[]', 1, 'test', '2026-09-29')"
        )
        for date, close, adj in rows:
            conn.execute(
                "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close,"
                " adjusted_close, volume, currency, source, fetched_at)"
                " VALUES ('X.HK', ?, ?, ?, ?, ?, ?, 0, 'HKD', 'test', '2026-09-29T00:00:00+00:00')",
                (date, close, close, close, close, adj),
            )

    class DS:
        def __init__(self, c):
            self._c = c

        @property
        def conn(self):
            return self._c

    # use the facade method directly through DataStore-like wrapper
    from stockinsider.data.store import DataStore

    ds = DataStore(conn)
    snapshot = ds.market_indicators_snapshot("X.HK")
    vol = snapshot["risk"]["volatility"]
    assert vol is not None and vol["value"] == 0.0  # adjusted series is flat


def test_day_change_plain_when_piped(monkeypatch) -> None:
    from stockinsider.cli.render import day_change_styled

    monkeypatch.setattr("sys.stdout", io.StringIO())  # not a tty
    line = "day change (2026-09-25 vs 2026-09-24): +1.23%"
    assert day_change_styled("0700.HK", line) == line  # N4: no ANSI when piped


def test_sessions_help_names_active() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "src" / "stockinsider" / "cli" / "app.py").read_text(encoding="utf-8")
    assert "active | closed" in text  # N5: help matches the real vocabulary
