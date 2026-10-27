"""TP-025 stage 5: E-013, an independent held-out remeasurement of phase 3 (stages 2-4).

The ledgers are produced by the real tools over a seeded store and frozen in
`fixtures/e013_ledgers.yaml`; a drift test rebuilds them. The battery
(`fixtures/e013_heldout.yaml`) was written by a separately briefed author from the
frozen ledgers alone and is never edited; owner rulings on its labels are an overlay.

Run `python test/offline/test_tp025_stage5_e013.py` to rewrite the frozen ledgers.

Implements: REQ-SI-INV-001, REQ-SI-QA-001 (ADR-008 phase 3, ADR-005 Am4; TP-025)
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

import yaml

from stockinsider.agent.registry import (
    Registry,
    register_data_tools,
    register_market_tools,
    register_news_tools,
    register_sync_tools,
)
from stockinsider.data.store import DataStore
from stockinsider.data.store.db import open_db
from stockinsider.data.store.vector import ensure_vec_table, insert_vectors
from stockinsider.shared.tools import ToolCall

FIXTURES = Path(__file__).parent / "fixtures"
LEDGER_FILE = FIXTURES / "e013_ledgers.yaml"
PLACEHOLDER = "9988.HK (name unverified - vendor search does not index this exchange; verify before adding)"

#: symbol -> (official name, exchange, verified, base close, amplitude, trend, currency, base volume)
SYMBOLS: dict[str, tuple[str, str, int, float, float, float, str, int]] = {
    "0700.HK": ("Tencent Holdings Ltd", "HK", 1, 612.0, 0.06, 0.08, "HKD", 15_400_000),
    "1211.HK": ("BYD Company Ltd", "HK", 1, 81.0, 0.11, -0.09, "HKD", 19_100_000),
    "AAPL.US": ("Apple Inc", "US", 1, 214.0, 0.05, 0.12, "USD", 52_300_000),
    "TGT.US": ("Target Corp", "US", 1, 148.0, 0.08, -0.05, "USD", 4_700_000),
    "9988.HK": (PLACEHOLDER, "HK", 0, 88.0, 0.09, 0.03, "HKD", 31_000_000),
}
#: symbol -> five quarters of (revenue, net income, gross profit), then (total assets, equity)
FUNDAMENTALS: dict[str, tuple[list[tuple[float, float, float]], tuple[float, float]]] = {
    "0700.HK": ([(161.1e9, 41.9e9, 84.2e9), (167.2e9, 47.6e9, 88.7e9), (172.4e9, 51.3e9, 91.0e9),
                 (180.0e9, 47.8e9, 95.6e9), (184.5e9, 55.6e9, 100.1e9)], (1.86e12, 1.02e12)),
    "1211.HK": ([(162.2e9, 6.8e9, 28.6e9), (201.1e9, 9.1e9, 35.2e9), (274.9e9, 15.0e9, 55.1e9),
                 (170.4e9, 9.2e9, 34.3e9), (200.9e9, 9.5e9, 37.9e9)], (8.10e11, 2.45e11)),
    "AAPL.US": ([(85.8e9, 21.4e9, 39.7e9), (94.9e9, 14.7e9, 43.9e9), (124.3e9, 36.3e9, 58.3e9),
                 (95.4e9, 24.8e9, 44.9e9), (94.0e9, 23.4e9, 43.7e9)], (3.31e11, 6.68e10)),
    "TGT.US": ([(25.5e9, 1.19e9, 7.30e9), (25.7e9, 0.85e9, 7.25e9), (30.9e9, 1.10e9, 8.02e9),
                (23.8e9, 1.04e9, 6.87e9), (25.2e9, 0.94e9, 7.11e9)], (5.80e10, 1.48e10)),
}
QUARTERS = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
#: news.recent rows for 0700.HK: (title, published, sentiment)
TENCENT_NEWS = [
    ("Tencent lifts buyback pace after quarterly results", "20261023T083000Z",
     {"polarity": 0.874, "neg": 0.031, "neu": 0.802, "pos": 0.167}),
    ("Tencent gaming revenue beats estimates on new titles", "20261022T101500Z",
     {"polarity": 0.912, "neg": 0.018, "neu": 0.776, "pos": 0.206}),
    ("Regulators review online game approvals in batch", "20261021T064500Z",
     {"polarity": -0.214, "neg": 0.094, "neu": 0.861, "pos": 0.045}),
]
#: news.search corpus: (bucket, title, vector)
SEARCH_NEWS = [
    ("1211.HK", "BYD October deliveries rise as export push continues", [1.0, 0.1, 0.0, 0.0]),
    ("0700.HK", "Tencent cloud unit signs regional data-centre deal", [0.9, 0.3, 0.0, 0.0]),
    ("macro:fed", "Federal Reserve holds rates as inflation cools", [0.7, 0.0, 0.7, 0.0]),
]
LAST_DAY = date(2026, 10, 23)
SESSIONS = 260


class _FixedProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


def _sessions() -> list[str]:
    days: list[str] = []
    day = LAST_DAY
    while len(days) < SESSIONS:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day -= timedelta(days=1)
    return list(reversed(days))


def _seed(conn: sqlite3.Connection) -> None:
    days = _sessions()
    with conn:
        for symbol, (name, exchange, verified, base, amp, trend, currency, volume) in SYMBOLS.items():
            conn.execute(
                "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified,"
                " source, resolved_at) VALUES (?, ?, ?, 'stock', '[]', ?, 'eodhd', '2026-10-01T00:00:00+00:00')",
                (symbol, exchange, name, verified),
            )
            for i, day in enumerate(days):
                close = round(base * (1 + amp * math.sin(i / 9.0) + trend * i / SESSIONS), 2)
                spread = round(close * 0.012, 2)
                conn.execute(
                    "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close, adjusted_close,"
                    " volume, currency, source, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'eodhd', '2026-10-24')",
                    (symbol, day, round(close - spread / 2, 2), round(close + spread, 2), round(close - spread, 2),
                     close, close, volume + (i * 7919) % 3_000_000, currency),
                )
        for symbol, (incomes, (assets, equity)) in FUNDAMENTALS.items():
            for period, (revenue, net, gross) in zip(QUARTERS, incomes):
                conn.execute(
                    "INSERT INTO fundamentals (canonical_symbol, period_end, statement_type, data, source,"
                    " fetched_at) VALUES (?, ?, 'income', ?, 'eodhd', '2026-10-24')",
                    (symbol, period, json.dumps({"totalRevenue": revenue, "netIncome": net, "grossProfit": gross})),
                )
            conn.execute(
                "INSERT INTO fundamentals (canonical_symbol, period_end, statement_type, data, source, fetched_at)"
                " VALUES (?, '2026-06-30', 'balance', ?, 'eodhd', '2026-10-24')",
                (symbol, json.dumps({"totalAssets": assets, "totalStockholdersEquity": equity})),
            )
        for symbol in ("0700.HK", "1211.HK", "AAPL.US", "TGT.US"):
            conn.execute(
                "INSERT INTO watchlist (canonical_symbol, added_at, added_via) VALUES (?, '2026-10-01', 'cli')",
                (symbol,),
            )
        for index, (title, published, sentiment) in enumerate(TENCENT_NEWS):
            conn.execute(
                "INSERT INTO news (url_norm, url_raw, title, domain, published_at, fetched_at, source_query, symbol,"
                " relevance_score, kept, sentiment, source) VALUES (?, ?, ?, 'reuters.com', ?,"
                " '2026-10-24T00:00:00+00:00', 'test', '0700.HK', 2.0, 1, ?, 'eodhd')",
                (f"https://news.example/t{index}", f"https://news.example/t{index}", title, published,
                 json.dumps(sentiment)),
            )
        start = 100
        for offset, (bucket, title, _vector) in enumerate(SEARCH_NEWS):
            conn.execute(
                "INSERT INTO news (news_id, url_norm, url_raw, title, domain, published_at, fetched_at, source_query,"
                " symbol, relevance_score, kept) VALUES (?, ?, ?, ?, 'reuters.com', '20261020T090000Z',"
                " '2026-10-24T00:00:00+00:00', 'test', ?, 2.0, 1)",
                (start + offset, f"https://news.example/s{offset}", f"https://news.example/s{offset}", title, bucket),
            )
    ensure_vec_table(conn, "e013-model", 4)
    insert_vectors(conn, "e013-model", [(start + i, vector) for i, (_b, _t, vector) in enumerate(SEARCH_NEWS)])


@contextmanager
def _pinned_env(root: Path) -> Iterator[None]:
    saved = {key: os.environ.get(key) for key in ("EODHD_DAILY_CALLS", "STOCKINSIDER_ENV_FILE")}
    os.environ["EODHD_DAILY_CALLS"] = "20"
    os.environ["STOCKINSIDER_ENV_FILE"] = str(root / "absent.env")
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def build_ledgers() -> dict[str, dict[str, Any]]:
    """Run the real tools over the seeded store and return the E-013 session ledgers."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with _pinned_env(root):
            conn = open_db(root / "e013.sqlite")
            try:
                _seed(conn)
                store = DataStore(conn)
                registry = Registry()
                register_data_tools(registry, store)
                register_sync_tools(registry, store)
                register_market_tools(registry, store)
                register_news_tools(registry, store, (_FixedProvider(), "e013-model"))

                def ledger(*calls: tuple[str, dict[str, Any]]) -> dict[str, Any]:
                    out: dict[str, Any] = {}
                    for seq, (tool, arguments) in enumerate(calls, start=1):
                        result = registry.execute(ToolCall(tool=tool, arguments=arguments, call_id=f"c{seq}"))
                        assert result.ok, (tool, result.error)
                        out[f"turn-0001/{tool}#{seq}"] = result.result
                    return json.loads(json.dumps(out))

                return {
                    "hk_pair": ledger(
                        ("market.quote", {"symbol": "0700.HK"}), ("market.quote", {"symbol": "1211.HK"}),
                        ("market.indicators", {"symbol": "0700.HK"}), ("market.indicators", {"symbol": "1211.HK"}),
                        ("news.recent", {"symbol": "0700.HK", "k": 3}),
                    ),
                    "us_pair": ledger(
                        ("market.quote", {"symbol": "AAPL.US"}), ("market.quote", {"symbol": "TGT.US"}),
                        ("market.indicators", {"symbol": "AAPL.US"}), ("market.indicators", {"symbol": "TGT.US"}),
                        ("fundamentals.summary", {"symbol": "AAPL.US"}),
                        ("fundamentals.summary", {"symbol": "TGT.US"}),
                    ),
                    "apple_only": ledger(
                        ("market.quote", {"symbol": "AAPL.US"}), ("market.indicators", {"symbol": "AAPL.US"}),
                    ),
                    "session": ledger(
                        ("watchlist.list", {}), ("sync.status", {}),
                        ("news.search", {"query": "Asian company news this week", "k": 3}),
                    ),
                    "unverified": ledger(("market.quote", {"symbol": "9988.HK"})),
                }
            finally:
                conn.close()


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_e013_ledgers_match_the_real_tools() -> None:
    assert _load(LEDGER_FILE)["ledgers"] == build_ledgers()


if __name__ == "__main__":
    header = (
        "# E-013 session ledgers (TP-025 stage 5): produced by the real tools over a seeded store.\n"
        "# Generated by test/offline/test_tp025_stage5_e013.py; do not edit by hand.\n"
    )
    body = yaml.safe_dump({"ledgers": build_ledgers()}, sort_keys=False, allow_unicode=False, width=120)
    LEDGER_FILE.write_text(header + body, encoding="utf-8", newline="\n")
    print(f"wrote {LEDGER_FILE}")
