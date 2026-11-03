"""Generate the frozen E-015 ledgers from the real tools over a seeded store.

Run once; the output is committed as test/offline/fixtures/e015_ledgers.yaml.
"""

import json
import math
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import yaml

from stockinsider.agent.registry import (
    Registry,
    register_market_tools,
    register_news_tools,
    register_performance_tools,
)
from stockinsider.data import open_data_store
from stockinsider.shared.tools import ToolCall

OUT = Path(sys.argv[1])
END = date(2026, 10, 2)


def weekdays(n: int) -> list[str]:
    out, day = [], END
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day -= timedelta(days=1)
    return list(reversed(out))


def closes(base: float, n: int, drift: float, swing: float, phase: float) -> list[float]:
    return [round(base * (1 + drift * (i - n) / n + swing * math.sin(i / 6.0 + phase)), 2) for i in range(n)]


SERIES = {
    "0700.HK": closes(420.0, 260, -0.06, 0.04, 0.3),
    "1211.HK": closes(74.0, 260, -0.12, 0.05, 1.1),
    "HSI.INDX": closes(23970.0, 260, -0.03, 0.02, 2.0),
}
NAMES = {"0700.HK": ("HK", "Tencent Holdings Ltd"), "1211.HK": ("HK", "BYD Company Ltd")}
NEWS = [
    ("Did Gas Vehicle Sales Just Dip Below 50% For The First Time?", "2026-10-02T13:05:00+00:00",
     {"polarity": -0.768, "neg": 0.224, "neu": 0.776, "pos": 0.0}),
    ("BYD, Leapmotor Continue EV Sales Streak; Tesla Deliveries On Deck", "2026-10-01T15:40:00+00:00",
     {"polarity": -0.422, "neg": 0.118, "neu": 0.882, "pos": 0.0}),
    ("BYD (SEHK:1211) Reshuffled Its Board And Committees", "2026-09-30T09:12:00+00:00",
     {"polarity": 0.966, "neg": 0.0, "neu": 0.861, "pos": 0.139}),
    ("3 Out-of-Favor Stocks with Warning Signs", "2026-09-29T11:20:00+00:00",
     {"polarity": 0.998, "neg": 0.071, "neu": 0.793, "pos": 0.136}),
    ("China Electric Vehicle Market Size and Forecast 2026-2030: 100+ KPIs on Powertrains", "2026-09-29T08:00:00+00:00",
     {"polarity": 0.999, "neg": 0.012, "neu": 0.874, "pos": 0.114}),
]

with tempfile.TemporaryDirectory() as tmp:
    store = open_data_store(str(Path(tmp) / "data"))
    conn = store._conn  # noqa: SLF001
    dates = weekdays(260)
    with conn:
        for symbol, (exchange, name) in NAMES.items():
            conn.execute(
                "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified,"
                " source, resolved_at) VALUES (?, ?, ?, 'stock', '[]', 1, 'eodhd-search', '2026-09-27T03:44:06+00:00')",
                (symbol, exchange, name),
            )
        for symbol, series in SERIES.items():
            currency = "POINTS" if symbol.endswith(".INDX") else "HKD"
            for i, (day, close) in enumerate(zip(dates, series)):
                conn.execute(
                    "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close, adjusted_close, volume,"
                    " currency, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'eodhd-eod', '2026-10-05')",
                    (symbol, day, round(close * 1.004, 2), round(close * 1.011, 2), round(close * 0.992, 2), close,
                     close, 15_000_000 + (i * 7919) % 9_000_000, currency),
                )
        for i, (title, published, sentiment) in enumerate(NEWS):
            conn.execute(
                "INSERT INTO news (url_norm, url_raw, title, domain, published_at, fetched_at, source_query, symbol,"
                " relevance_score, kept, sentiment, source) VALUES (?, ?, ?, 'finance.yahoo.com', ?, '2026-10-05',"
                " 'eodhd', '1211.HK', 1.0, 1, ?, 'eodhd')",
                (f"finance.yahoo.com/n{i}", f"https://finance.yahoo.com/n{i}", title, published, json.dumps(sentiment)),
            )
    reg = Registry()
    register_market_tools(reg, store)
    register_performance_tools(reg, store)
    register_news_tools(reg, store)

    def run(tool: str, **args):
        result = reg.execute(ToolCall(tool=tool, arguments=args, call_id="gen"))
        assert result.ok, result.error
        return json.loads(json.dumps(result.result))

    ledgers = {
        "byd_report": {
            "turn-0001/market.quote#1": run("market.quote", symbol="1211.HK"),
            "turn-0001/market.indicators#2": run("market.indicators", symbol="1211.HK"),
            "turn-0001/fundamentals.summary#3": run("fundamentals.summary", symbol="1211.HK"),
            "turn-0001/news.recent#4": run("news.recent", symbol="1211.HK", k=5),
        },
        "perf_pair": {
            "turn-0001/market.quote#1": run("market.quote", symbol="0700.HK"),
            "turn-0001/market.quote#2": run("market.quote", symbol="HSI.INDX"),
            "turn-0001/market.performance#3": run("market.performance", symbol="0700.HK"),
            "turn-0001/market.performance#4": run("market.performance", symbol="HSI.INDX"),
            "turn-0001/market.indicators#5": run("market.indicators", symbol="0700.HK"),
        },
    }
    store.close()

header = (
    "# E-015 frozen ledgers (TP-042): real tool results over a seeded store, generated once by\n"
    "# the rule author's script; the battery author reads only these and the brief.\n"
)
OUT.write_text(header + yaml.safe_dump({"ledgers": ledgers}, sort_keys=False, allow_unicode=False, width=110), encoding="utf-8")
print("written", OUT)
