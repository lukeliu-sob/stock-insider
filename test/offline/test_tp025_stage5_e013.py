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
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

import yaml

from stockinsider.agent import guardrail
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


# ---- battery, label check, measurement ------------------------------------------

BATTERY_FILE = FIXTURES / "e013_heldout.yaml"
CLASSES = ("name_misattribution", "postposed_subject", "absent_company", "unverified_name", "common_word_name", "table")
#: kinds whose value must not be in the ledger at all (fabricated, too precise, computed)
ABSENT_KINDS = {"fabricated", "over_precise", "derived", "no_evidence"}
_SCALE_WORDS = {
    "thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9,
    "trillion": 1e12, "tn": 1e12,
}
_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
    "december",
)
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.(\d+))?")
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_MDY = re.compile(r"([A-Za-z]+)\.? (\d{1,2}),? (\d{4})")
_DMY = re.compile(r"(\d{1,2}) ([A-Za-z]+),? (\d{4})")


def _ledger_numbers(node: Any, out: list[float]) -> None:
    """Every numeric leaf and numeric string in a ledger, plus every list length (counts)."""
    if isinstance(node, dict):
        for value in node.values():
            _ledger_numbers(value, out)
    elif isinstance(node, list):
        out.append(float(len(node)))
        for value in node:
            _ledger_numbers(value, out)
    elif isinstance(node, bool) or node is None:
        return
    elif isinstance(node, (int, float)):
        out.append(float(node))
    elif isinstance(node, str) and _NUMBER.fullmatch(node.strip()):
        out.append(float(node.strip().replace(",", "")))


def _ledger_dates(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _ledger_dates(value, out)
    elif isinstance(node, list):
        for value in node:
            _ledger_dates(value, out)
    elif isinstance(node, str):
        compact = node.replace("-", "")[:8]
        if len(compact) == 8 and compact.isdigit():
            out.add(f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}")


def _month(word: str) -> int | None:
    prefix = word.lower()[:3]
    return next((index for index, name in enumerate(_MONTHS, start=1) if name.startswith(prefix)), None)


def _as_date(raw: str) -> str | None:
    text = raw.strip().rstrip(".,")
    if _ISO_DATE.fullmatch(text):
        return text
    for pattern, month_group, day_group in ((_MDY, 1, 2), (_DMY, 2, 1)):
        match = pattern.fullmatch(text)
        if match and _month(match.group(month_group)):
            return f"{match.group(3)}-{_month(match.group(month_group)):02d}-{int(match.group(day_group)):02d}"
    return None


def _claimed_value(raw: str, after: str) -> tuple[float, float] | None:
    """(value, half-width at the written precision) of a claim, with a following scale word applied."""
    match = _NUMBER.search(raw)
    if not match:
        return None
    value = float(match.group(0).replace(",", ""))
    decimals = len(match.group(1) or "")
    rest = raw[match.end():]
    word = re.match(r"\s*([A-Za-z]+)", rest if rest.strip() else after)
    scale = _SCALE_WORDS.get(word.group(1).lower(), 1.0) if word else 1.0
    return value * scale, 0.5 * 10**-decimals * scale


def _value_in_ledger(claim: tuple[float, float], numbers: list[float]) -> bool:
    value, half = claim
    for number in numbers:
        for candidate in (abs(number), abs(number) * 100):
            if abs(candidate - abs(value)) <= half + 1e-9 * max(1.0, candidate):
                return True
    return False


def label_disagreements(battery: dict, ledgers: dict) -> list[tuple[str, str, str]]:
    """Labels the ledger values contradict, checked without the engine (stage-5 step 3).

    A claim labeled correct whose value is nowhere in the cited ledger, and a claim labeled
    fabricated, over-precise, derived or no-evidence whose value is in it, are disagreements.
    Attribution (which subject, which field) is not checked mechanically.
    """
    found: list[tuple[str, str, str]] = []
    for item in battery["items"]:
        ledger = ledgers[item["ledger"]]
        numbers: list[float] = []
        _ledger_numbers(ledger, numbers)
        dates: set[str] = set()
        _ledger_dates(ledger, dates)
        text = item["text"]
        position = 0
        for label in item["claims"]:
            start = text.find(label["text"], position)
            position = start + len(label["text"])
            key = (item["id"], label["text"])
            as_date = _as_date(label["text"])
            if as_date is not None or label.get("kind") == "temporal":
                if as_date is None:
                    found.append((*key, "date not parsed by the checker"))
                elif label["correct"] and as_date not in dates:
                    found.append((*key, "labeled correct, date not in ledger"))
                continue
            claim = _claimed_value(label["text"], text[position:])
            if claim is None:
                found.append((*key, "no number parsed"))
            elif label["correct"] and not _value_in_ledger(claim, numbers):
                found.append((*key, "labeled correct, value not in ledger"))
            elif not label["correct"] and label.get("kind") in ABSENT_KINDS and _value_in_ledger(claim, numbers):
                found.append((*key, f"labeled {label.get('kind')}, value is in ledger"))
    return found


#: Owner rulings on mechanical disagreements: (item, claim text) -> "label stands" | "correct" | "wrong".
#: Owner, 2026-10-27: all nine are checker limits, every label stands - absent-company claims tagged
#: no_evidence whose value belongs to another company (E011, E013), a scale stated in a table title
#: (E026), and a wrong-field count tagged fabricated (E046: 13 is the gap count, 12 cells are filled).
#: The author's unverified_name rule (labeled by value against the 9988.HK quote) is accepted.
LABEL_RULINGS: dict[tuple[str, str], str] = {
    ("E011", "35.0%"): "label stands",
    ("E013", "5.45%"): "label stands",
    ("E026", "94.0"): "label stands",
    ("E026", "23.4"): "label stands",
    ("E026", "43.7"): "label stands",
    ("E026", "25.2"): "label stands",
    ("E026", "7.11"): "label stands",
    ("E026", "14.8"): "label stands",
    ("E046", "13"): "label stands",
}


def _specs() -> dict:
    registry = Registry()
    register_data_tools(registry, None)
    register_sync_tools(registry, None)
    register_market_tools(registry, None)
    register_news_tools(registry, None, (_FixedProvider(), "e013-model"))
    return {spec.name: spec for spec in registry.list_tools()}


def evaluate(battery: dict, ledgers: dict) -> dict[str, Any]:
    """Per-claim outcome on the production post-check path (with the declared specs)."""
    specs = _specs()
    found: dict[str, Any] = {
        "correct": [], "wrong": [], "false_flags": [], "escapes": [], "extra_flags": [], "by_class": {},
    }
    for item in battery["items"]:
        text = item["text"]
        claims = list(guardrail.postcheck_numbers(text, ledgers[item["ledger"]], specs).claims)
        used: set[int] = set()
        position = 0
        for label in item["claims"]:
            start = text.find(label["text"], position)
            position = start + len(label["text"])
            overlapping = [i for i, c in enumerate(claims) if c.start < position and c.end > start]
            used.update(overlapping)
            flagged = any(not claims[i].verified for i in overlapping)
            key = (item["id"], label["text"])
            ruling = LABEL_RULINGS.get(key, "label stands")
            correct = label["correct"] if ruling == "label stands" else ruling == "correct"
            tally = found["by_class"].setdefault(
                label.get("class", "general"), {"correct": 0, "wrong": 0, "false_flags": 0, "escapes": 0}
            )
            outcome = ("correct", "false_flags", flagged) if correct else ("wrong", "escapes", not flagged)
            found[outcome[0]].append(key)
            tally[outcome[0]] += 1
            if outcome[2]:
                found[outcome[1]].append(key)
                tally[outcome[1]] += 1
        found["extra_flags"] += [(item["id"], c.raw) for i, c in enumerate(claims) if i not in used and not c.verified]
    return found


if __name__ == "__main__":
    header = (
        "# E-013 session ledgers (TP-025 stage 5): produced by the real tools over a seeded store.\n"
        "# Generated by test/offline/test_tp025_stage5_e013.py; do not edit by hand.\n"
    )
    body = yaml.safe_dump({"ledgers": build_ledgers()}, sort_keys=False, allow_unicode=False, width=120)
    LEDGER_FILE.write_text(header + body, encoding="utf-8", newline="\n")
    print(f"wrote {LEDGER_FILE}")


def test_e013_battery_shape() -> None:
    battery = _load(BATTERY_FILE)
    claims = [(item, label) for item in battery["items"] for label in item["claims"]]
    assert len(claims) >= 80
    assert sum(not label["correct"] for _, label in claims) >= 35
    for name in CLASSES:
        assert sum(label.get("class") == name for _, label in claims) >= 5, name
    for item, label in claims:
        assert item["text"].count(label["text"]) == 1, (item["id"], label["text"])
        assert item["ledger"] in _load(LEDGER_FILE)["ledgers"], item["id"]


def test_e013_labels_agree_with_ledgers() -> None:
    disagreements = label_disagreements(_load(BATTERY_FILE), _load(LEDGER_FILE)["ledgers"])
    unresolved = [entry for entry in disagreements if entry[:2] not in LABEL_RULINGS]
    assert unresolved == []
    assert {entry[:2] for entry in disagreements} == set(LABEL_RULINGS)


#: E-013 measured on the frozen stage-4 engine (2026-10-27), pinned by name as a regression baseline.
#: No threshold was set in advance (owner decision); any change to these sets is visible here.
E013_ESCAPES = {
    ("E007", "6.35%"), ("E051", "3.88%"),  # subject after the number ("ROE at Apple", "for Tencent")
    ("E011", "35.0%"),  # company absent from the ledger (DE-16 residual)
    ("E030", "0.206"), ("E037", "0.3162"),  # which list item a value belongs to
}
E013_FALSE_FLAGS = {
    ("E003", "6.35%"), ("E007", "3.73%"), ("E009", "14.53%"), ("E051", "4.73%"),  # subject after the number
    ("E001", "23.9%"), ("E003", "9.56%"), ("E022", "9.56%"), ("E047", "1.18%"), ("E049", "9.6%"),  # "year on year"
    ("E026", "25.2"), ("E026", "7.11"), ("E026", "14.8"),  # "Target" row read as a price-target cue
    ("E027", "134.11"), ("E027", "136.54"), ("E027", "133.3"),
    ("E026", "94.0"), ("E026", "23.4"), ("E026", "43.7"),  # scale stated in the table title
    ("E043", "36.3 billion"), ("E043", "331 billion"),  # a cue after the next number; total assets untyped
}


def test_e013_heldout_measurement() -> None:
    result = evaluate(_load(BATTERY_FILE), _load(LEDGER_FILE)["ledgers"])
    assert (len(result["correct"]), len(result["wrong"])) == (109, 53)
    assert set(result["escapes"]) == E013_ESCAPES, sorted(set(result["escapes"]) ^ E013_ESCAPES)
    assert set(result["false_flags"]) == E013_FALSE_FLAGS, sorted(set(result["false_flags"]) ^ E013_FALSE_FLAGS)
    assert result["extra_flags"] == []
    for name, tally in sorted(result["by_class"].items()):
        print(name, tally)
