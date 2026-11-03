"""TP-042: post-check false flags seen in live use (E-015).

Unit cases run on the frozen E-015 ledgers, real tool results over a seeded store with the
shapes of the 2026-11-03 live session. E-015, written by a separately briefed author before the
rule code, measures the change; its pins are a regression baseline.

Implements: REQ-SI-INV-001, REQ-SI-QA-001 (ADR-008 Am3; TP-042)
"""

from __future__ import annotations

import json
import math
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from test_tp025_stage5_e013 import FIXTURES, _load, _specs, evaluate, label_disagreements

from stockinsider.agent import guardrail
from stockinsider.agent.registry import (
    Registry,
    register_market_tools,
    register_news_tools,
    register_performance_tools,
)
from stockinsider.data import open_data_store
from stockinsider.shared.tools import ToolCall

LEDGER_FILE = FIXTURES / "e015_ledgers.yaml"
E015_FILE = FIXTURES / "e015_heldout.yaml"
E015_CLASSES = (
    "inline_list", "table_count", "reference", "quoted_title", "sentiment_component", "decline_sign",
)

# ---- the frozen ledgers ------------------------------------------------------------

_END = date(2026, 10, 2)
_NAMES = {"0700.HK": ("HK", "Tencent Holdings Ltd"), "1211.HK": ("HK", "BYD Company Ltd")}
_NEWS = [
    ("Did Gas Vehicle Sales Just Dip Below 50% For The First Time?", "2026-10-02T13:05:00+00:00",
     {"polarity": -0.768, "neg": 0.224, "neu": 0.776, "pos": 0.0}),
    ("BYD, Leapmotor Continue EV Sales Streak; Tesla Deliveries On Deck", "2026-10-01T15:40:00+00:00",
     {"polarity": -0.422, "neg": 0.118, "neu": 0.882, "pos": 0.0}),
    ("BYD (SEHK:1211) Reshuffled Its Board And Committees", "2026-09-30T09:12:00+00:00",
     {"polarity": 0.966, "neg": 0.0, "neu": 0.861, "pos": 0.139}),
    ("3 Out-of-Favor Stocks with Warning Signs", "2026-09-29T11:20:00+00:00",
     {"polarity": 0.998, "neg": 0.071, "neu": 0.793, "pos": 0.136}),
    ("China Electric Vehicle Market Size and Forecast 2026-2030: 100+ KPIs on Powertrains",
     "2026-09-29T08:00:00+00:00", {"polarity": 0.999, "neg": 0.012, "neu": 0.874, "pos": 0.114}),
]


def _weekdays(n: int) -> list[str]:
    out, day = [], _END
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day -= timedelta(days=1)
    return list(reversed(out))


def _closes(base: float, n: int, drift: float, swing: float, phase: float) -> list[float]:
    return [round(base * (1 + drift * (i - n) / n + swing * math.sin(i / 6.0 + phase)), 2) for i in range(n)]


def build_ledgers() -> dict[str, dict[str, Any]]:
    """Run the real tools over the seeded store and return the E-015 session ledgers."""
    series = {
        "0700.HK": _closes(420.0, 260, -0.06, 0.04, 0.3),
        "1211.HK": _closes(74.0, 260, -0.12, 0.05, 1.1),
        "HSI.INDX": _closes(23970.0, 260, -0.03, 0.02, 2.0),
    }
    with tempfile.TemporaryDirectory() as tmp:
        store = open_data_store(str(Path(tmp) / "data"))
        conn = store._conn  # noqa: SLF001
        dates = _weekdays(260)
        with conn:
            for symbol, (exchange, name) in _NAMES.items():
                conn.execute(
                    "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified,"
                    " source, resolved_at) VALUES (?, ?, ?, 'stock', '[]', 1, 'eodhd-search',"
                    " '2026-09-27T03:44:06+00:00')",
                    (symbol, exchange, name),
                )
            for symbol, closes in series.items():
                currency = "POINTS" if symbol.endswith(".INDX") else "HKD"
                for i, (day, close) in enumerate(zip(dates, closes)):
                    conn.execute(
                        "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close, adjusted_close,"
                        " volume, currency, source, fetched_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'eodhd-eod', '2026-10-05')",
                        (symbol, day, round(close * 1.004, 2), round(close * 1.011, 2), round(close * 0.992, 2),
                         close, close, 15_000_000 + (i * 7919) % 9_000_000, currency),
                    )
            for i, (title, published, sentiment) in enumerate(_NEWS):
                conn.execute(
                    "INSERT INTO news (url_norm, url_raw, title, domain, published_at, fetched_at, source_query,"
                    " symbol, relevance_score, kept, sentiment, source) VALUES (?, ?, ?, 'finance.yahoo.com', ?,"
                    " '2026-10-05', 'eodhd', '1211.HK', 1.0, 1, ?, 'eodhd')",
                    (f"finance.yahoo.com/n{i}", f"https://finance.yahoo.com/n{i}", title, published,
                     json.dumps(sentiment)),
                )
        registry = Registry()
        register_market_tools(registry, store)
        register_performance_tools(registry, store)
        register_news_tools(registry, store)

        def run(tool: str, **args: Any) -> Any:
            result = registry.execute(ToolCall(tool=tool, arguments=args, call_id="e015"))
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
    return ledgers


LEDGERS = _load(LEDGER_FILE)["ledgers"]
BYD, PERF = LEDGERS["byd_report"], LEDGERS["perf_pair"]


def test_e015_ledgers_match_the_real_tools() -> None:
    assert LEDGERS == build_ledgers()


# ---- unit cases --------------------------------------------------------------------


def _verdicts(text: str, ledger: dict) -> dict[str, bool]:
    return {claim.raw: claim.verified for claim in guardrail.postcheck_numbers(text, ledger, _specs()).claims}


def _quote(ledger: dict, key: str) -> dict:
    return ledger[key]


def _window(ledger: dict, key: str, sessions: int) -> dict:
    return next(row for row in ledger[key]["windows"] if row["sessions"] == sessions)


def test_middle_dot_ends_a_cue() -> None:
    bar = _quote(BYD, "turn-0001/market.quote#1")
    good = f"BYD's last bar: Open {bar['open']} · High {bar['high']} · Low {bar['low']} · Close {bar['close']}."
    swapped = f"BYD's last bar: Open {bar['open']} · High {bar['low']} · Low {bar['high']} · Close {bar['close']}."
    assert all(_verdicts(good, BYD).values()), _verdicts(good, BYD)
    flagged = _verdicts(swapped, BYD)
    assert not flagged[str(bar["low"])] and not flagged[str(bar["high"])]


def test_count_noun_beats_row_label_in_tables() -> None:
    volatility = BYD["turn-0001/market.indicators#2"]["risk"]["volatility"]
    sessions = volatility["window"]["sessions"]
    pct = f"{volatility['value'] * 100:.2f}%"
    table = f"| Metric | Value | Window |\n|---|---|---|\n| Annualized volatility | {pct} | {sessions} sessions |"
    verdicts = _verdicts(table, BYD)
    assert all(verdicts.values()), verdicts
    wrong = table.replace(pct, "12.5%")
    assert not _verdicts(wrong, BYD)["12.5"]


def test_section_and_list_numbers_are_identifiers() -> None:
    bar = _quote(BYD, "turn-0001/market.quote#1")
    text = (
        f"As noted in §2, BYD closed at {bar['close']}. Next steps: (1) confirm the listing; (2) run a sync; "
        f"3) review the headlines."
    )
    raws = set(_verdicts(text, BYD))
    assert raws == {str(bar["close"])}, raws
    assert not _verdicts("BYD moved (2.5%) on the day.", BYD)["2.5"]


def test_backtick_and_table_cell_titles_are_quotations() -> None:
    title = "Did Gas Vehicle Sales Just Dip Below 50% For The First Time?"
    assert all(_verdicts(f"The newest headline is `{title}`.", BYD).values())
    cell = f"| Date | Title |\n|---|---|\n| 2026-10-02 | {title} |"
    assert all(_verdicts(cell, BYD).values()), _verdicts(cell, BYD)
    altered = cell.replace("50%", "40%")
    assert not _verdicts(altered, BYD)["40"]
    assert not _verdicts("Gas vehicle sales fell below 50% of the market.", BYD)["50"]


def test_key_name_before_number_types_it() -> None:
    good = "The 2026-10-02 headline carries polarity -0.768, with neg 0.224 and neu 0.776."
    assert all(_verdicts(good, BYD).values()), _verdicts(good, BYD)
    wrong = "The 2026-10-02 headline carries polarity -0.768, with neg 0.776 and neu 0.224."
    verdicts = _verdicts(wrong, BYD)
    assert not verdicts["0.776"] and not verdicts["0.224"]


def test_decline_sign_goes_to_the_percent() -> None:
    month = _window(PERF, "turn-0001/market.performance#3", 20)
    assert month["change_pct"] < 0
    fall = f"{abs(month['change_pct']):.2f}"
    good = f"Tencent fell {fall}% over the last 20 sessions."
    assert all(_verdicts(good, PERF).values()), _verdicts(good, PERF)
    assert not _verdicts(f"Tencent rose {fall}% over the last 20 sessions.", PERF)[fall]
    week = _window(PERF, "turn-0001/market.performance#3", 5)
    assert week["change_pct"] > 0
    rise = f"{week['change_pct']:.2f}"
    assert all(_verdicts(f"Tencent rose {rise}% over 5 sessions.", PERF).values())
    assert not _verdicts(f"Tencent fell {rise}% over 5 sessions.", PERF)[rise]


# ---- E-015 ------------------------------------------------------------------------

#: The mechanical label check's disagreements (TP-025 stage-5 method), for the owner to rule on
#: in the PR. The agent's recommendation is that every label stands: identifiers (§2, (2), Step 3)
#: and digits of a quoted title are by definition not ledger values; G031's "100" and G037's
#: "0.12" are a title's digits used as data and a fabricated neg share (0.012 is stored); "29
#: September" and "2 Oct" are dates the mechanical parser does not read.
E015_RULINGS: dict[tuple[str, str], str] = {
    key: "label stands"
    for key in (
        ("G015", "§2"), ("G015", "(2)"), ("G016", "§4"), ("G016", "2)"), ("G019", "2)"), ("G019", "3)"),
        ("G020", "Step 3"), ("G020", "§6"), ("G023", "50%"), ("G024", "3"), ("G025", "2026-2030"),
        ("G025", "29 September"), ("G026", "50%"), ("G026", "3"), ("G031", "100"), ("G032", "2026-2030"),
        ("G032", "50%"), ("G037", "0.12"), ("G057", "2 Oct"),
    )
}

#: E-015 on the pre-change engine (this branch's base, 2026-11-03): precision 109/173, recall 39/50.
#: First run on the changed engine: precision 169/173, recall 43/50 - two new escapes (G018 6.58%,
#: G045 10.61%: a change given to the wrong window) and one old one (G052: the index's change given
#: to Tencent) exposed that index results had no subject and that windows were not checked. Both
#: were fixed and disclosed (TP-042 amendment), so the numbers below are no longer independent.
E015_FALSE_FLAGS = {
    ("G019", "8"),  # quarters_expected is bookkeeping, typed inert by design
    ("G025", "29 September"), ("G057", "2 Oct"),  # a date written without its year
    ("G029", "100"),  # the quoted title has another digit altered, so the whole quotation fails
    ("G047", "+2.31%"),  # subject written after the number ("for the index"; DE-15 residual)
}
E015_ESCAPES = {
    ("G011", "259"),  # a session count that exists elsewhere in the ledger (the volatility window)
    ("G037", "0.12"),  # rounds to another headline's neg share (0.118); a headline is not a subject
    ("G063", "440.81"),  # which window's base close a value is (window attribution of closes)
}


def test_e015_battery_shape() -> None:
    battery = _load(E015_FILE)
    claims = [(item, label) for item in battery["items"] for label in item["claims"]]
    assert len(claims) >= 80
    assert sum(not label["correct"] for _, label in claims) >= 30
    for name in E015_CLASSES:
        assert sum(label.get("class") == name for _, label in claims) >= 8, name
    for item, label in claims:
        assert item["text"].count(label["text"]) == 1, (item["id"], label["text"])
        assert item["ledger"] in LEDGERS, item["id"]


def test_e015_labels_agree_with_ledgers() -> None:
    disagreements = label_disagreements(_load(E015_FILE), LEDGERS)
    assert {entry[:2] for entry in disagreements} == set(E015_RULINGS)


def test_e015_heldout_measurement() -> None:
    result = evaluate(_load(E015_FILE), LEDGERS, E015_RULINGS)
    assert (len(result["correct"]), len(result["wrong"])) == (173, 50)
    assert set(result["false_flags"]) == E015_FALSE_FLAGS, sorted(set(result["false_flags"]) ^ E015_FALSE_FLAGS)
    assert set(result["escapes"]) == E015_ESCAPES, sorted(set(result["escapes"]) ^ E015_ESCAPES)
    assert result["extra_flags"] == []
    for name, tally in sorted(result["by_class"].items()):
        print(name, tally)


def test_index_results_are_subjects() -> None:
    """A change of the index given to Tencent is flagged; the same change given to the index verifies."""
    index_month = _window(PERF, "turn-0001/market.performance#4", 20)
    claimed = f"{index_month['change_pct']:.2f}"
    assert all(_verdicts(f"The index gained {claimed}% over the last 20 sessions.", PERF).values())
    assert not _verdicts(f"Tencent gained {claimed}% over the last 20 sessions.", PERF)[claimed]


def test_stated_window_selects_the_change() -> None:
    quarter = _window(PERF, "turn-0001/market.performance#3", 60)
    claimed = f"{abs(quarter['change_pct']):.2f}"
    assert all(_verdicts(f"Tencent fell {claimed}% over 60 sessions.", PERF).values())
    assert not _verdicts(f"Tencent fell {claimed}% over 20 sessions.", PERF)[claimed]


def test_change_word_signs_only_the_next_number() -> None:
    """"fell" signs 4.88, not the index's 3.34 written after it (no count noun to excuse it)."""
    month = _window(PERF, "turn-0001/market.performance#3", 20)
    index_month = _window(PERF, "turn-0001/market.performance#4", 20)
    fall, rise = f"{abs(month['change_pct']):.2f}", f"{index_month['change_pct']:.2f}"
    verdicts = _verdicts(f"Over 20 sessions Tencent fell {fall}% and HSI {rise}%.", PERF)
    assert verdicts[fall] and verdicts[rise], verdicts
