"""INV-001 v2 phase 2: typed numeric claims (ADR-008 Amendment 1, TP-024).

v1 checked every digit run against one flat pool of evidence numbers.
Phase 2 reads an answer as numeric claims. Each number gets a claim
class - structural, identifier, quoted, temporal or quantitative - and
is checked by the rule of its class:

- a quantitative claim with a field cue is compared only with evidence
  of its subject and field class, at the precision it is written
  (units, scale words, decline sign, rounding to the last written digit);
- one without a field keeps the v1 rule, so the check is never looser
  than v1 there;
- temporal claims are parsed whole and compared in UTC at their written
  precision; a month, quarter or year may also overlap a returned window;
- a number inside a quotation verifies when the quotation is tool text.

Positions are kept against the original text (handled regions are
blanked to the same length), so the unverified marker can go after
exactly the claims that failed. Evidence is typed from the session
ledger's key names - a heuristic until phase 3 declares field semantics
(DE-15).

Implements: REQ-SI-INV-001 (ADR-008)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from stockinsider.agent import guardrail as v1

# ---- vocabulary (TP-024 Appendix A; heuristic until TP-025) ----------------

#: Display names of the field classes, used in reasons.
FIELD_NAMES: dict[str, str] = {
    "price": "price",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "adjusted_close": "adjusted close",
    "volume": "volume",
    "volatility": "volatility",
    "drawdown": "drawdown",
    "roe": "ROE",
    "net_margin": "net margin",
    "gross_margin": "gross margin",
    "revenue_growth": "revenue growth",
    "pe": "P/E",
    "pb": "P/B",
    "ps": "P/S",
    "sentiment": "sentiment score",
    "sentiment_positive": "positive sentiment share",
    "sentiment_negative": "negative sentiment share",
    "sentiment_neutral": "neutral sentiment share",
    "margin": "margin",
    "sessions": "session count",
    "news_count": "news count",
    "symbol_count": "symbol count",
    "gaps": "gap count",
    "tokens": "token budget",
    "api_calls": "API call count",
    "api_calls_used": "API calls used",
    "api_calls_remaining": "remaining API calls",
    "api_calls_cap": "API call cap",
    "api_calls_run": "API calls of the last sync run",
    "revenue": "revenue",
    "net_income": "net income",
    "gross_profit": "gross profit",
    "equity": "equity",
    "target": "price target",
}
_PRICE_FIELDS = frozenset({"open", "high", "low", "close", "adjusted_close"})
#: Fields whose values are fractions: a percent claim compares value x 100.
_FRACTION_FIELDS = frozenset(
    {
        "volatility", "drawdown", "roe", "net_margin", "gross_margin", "revenue_growth", "sentiment",
        "sentiment_positive", "sentiment_negative", "sentiment_neutral",
    }
)
#: A claimed generic class -> the evidence classes it covers.
_FAMILIES: dict[str, frozenset[str]] = {
    "price": _PRICE_FIELDS,
    "margin": frozenset({"net_margin", "gross_margin"}),
    "api_calls": frozenset({"api_calls_used", "api_calls_remaining", "api_calls_cap", "api_calls_run"}),
    "api_calls_used": frozenset({"api_calls_used", "api_calls_run"}),
}
#: Words near a generic count that narrow it to one evidence class.
_REFINEMENTS: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "api_calls": (
        ("api_calls_remaining", re.compile(r"\b(?:remain(?:s|ing)?|left|leaves|leaving)\b", re.IGNORECASE)),
        ("api_calls_cap", re.compile(r"\b(?:cap|caps|capped|limit|ceiling|allowance)\b", re.IGNORECASE)),
        ("api_calls_run", re.compile(r"\b(?:last|latest|previous)\s+(?:sync\s+)?run\b", re.IGNORECASE)),
        ("api_calls_used", re.compile(r"\b(?:used|consumed|spent|uses|using)\b", re.IGNORECASE)),
    ),
}

#: Evidence key -> field class.
_KEY_FIELDS: dict[str, str] = {
    "open": "open",
    "open_price": "open",
    "day_open": "open",
    "high": "high",
    "day_high": "high",
    "low": "low",
    "day_low": "low",
    "close": "close",
    "close_price": "close",
    "last_close": "close",
    "prev_close": "close",
    "previous_close": "close",
    "adjusted_close": "adjusted_close",
    "adj_close": "adjusted_close",
    "volume": "volume",
    "sessions": "sessions",
    "polarity": "sentiment",
    "neg": "sentiment_negative",
    "neu": "sentiment_neutral",
    "pos": "sentiment_positive",
    "compound": "sentiment",
    "max_session_tokens": "tokens",
    "tokens": "tokens",
    "totalrevenue": "revenue",
    "revenue": "revenue",
    "netincome": "net_income",
    "net_income": "net_income",
    "grossprofit": "gross_profit",
    "gross_profit": "gross_profit",
    "totalstockholdersequity": "equity",
    "equity": "equity",
    "active_symbols": "symbol_count",
    "calls_used": "api_calls_run",
}
#: Indicator metric names (the `metric` sibling of a `value`, or the key).
_METRIC_FIELDS: dict[str, str] = {
    "volatility": "volatility",
    "max_drawdown": "drawdown",
    "drawdown": "drawdown",
    "roe": "roe",
    "net_margin": "net_margin",
    "gross_margin": "gross_margin",
    "yoy_growth": "revenue_growth",
    "revenue_yoy": "revenue_growth",
    "pe": "pe",
    "pb": "pb",
    "ps": "ps",
}
#: Keys of real tool results that hold bookkeeping numbers a claim never
#: cites: typed "other", so they stay incompatible with every claimed field.
_INERT_KEYS = frozenset(
    {"quarters", "quarters_expected", "cells", "run_id", "distance", "news_id", "id", "k"}
)

#: The noun after "positive" / "negative" / "neutral" that names a sentiment component.
_SENTIMENT_PART = r"(?:sentiment\s+)?(?:components?|shares?|scores?|readings?|portions?|weights?)\b"

#: Claim-side field cues (same clause as the number).
_CUE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("adjusted_close", r"\badj(?:usted)?[\s_.]*clos(?:e|ing)\b"),
    (
        "close",
        r"\b(?:last|previous|prior|prev)[\s_]+close\b|\bclos(?:e|es|ed|ing)\b(?!\s+to\b)(?:[\s_]+price)?"
        r"|\b(?:settl|finish|end)(?:ed|ing|es|s)?\s+(?:the\s+(?:day|session)\s+)?at\b",
    ),
    ("open", r"\bopen(?:ed|ing)?\b(?:[\s_]+price)?"),
    (
        "high",
        r"\b(?:the|a|its|day|intraday|session|daily|52-week)[\s_]+highs?\b|\bhighs?\s+(?:of|was|at|is)\b"
        r"|\bpeaked\s+at\b",
    ),
    (
        "low",
        r"\b(?:the|a|its|day|intraday|session|daily|52-week)[\s_]+lows?\b|\blows?\s+(?:of|was|at|is)\b"
        r"|\bbottomed\s+(?:out\s+)?at\b",
    ),
    ("volume", r"\bvolumes?\b|\bshares?\s+traded\b|\btraded\s+shares\b"),
    ("volatility", r"\bvolatility\b|\bswings?\b|\bfluctuations?\b"),
    (
        "drawdown",
        r"\b(?:max(?:imum)?[\s_]+)?drawdowns?\b|\bfrom\s+(?:its|the)\s+peak\b|\bpeak[\s-]+to[\s-]+trough\b"
        r"|\b(?:deepest|largest|biggest|worst|steepest|maximum|max)\s+(?:declines?|drops?|falls?|loss(?:es)?)\b",
    ),
    ("roe", r"\bROE\b|\breturn\s+on\s+equity\b"),
    ("net_margin", r"\bnet\s+(?:profit\s+)?margins?\b"),
    ("gross_margin", r"\bgross\s+margins?\b"),
    ("revenue_growth", r"\brevenue\s+growth\b|\bYoY\b|\byear[\s-]+over[\s-]+year\b|\by/y\b"),
    ("pe", r"\bP/?E\b(?:\s+ratio)?|\bprice[\s-]+to[\s-]+earnings\b|\bearnings\s+multiple\b"),
    ("pb", r"\bP/?B\b(?:\s+ratio)?|\bprice[\s-]+to[\s-]+book\b"),
    ("ps", r"\bP/?S\b(?:\s+ratio)?|\bprice[\s-]+to[\s-]+sales\b"),
    ("sentiment_positive", rf"\bpositive\s+{_SENTIMENT_PART}"),
    ("sentiment_negative", rf"\bnegative\s+{_SENTIMENT_PART}"),
    ("sentiment_neutral", rf"\bneutral\s+{_SENTIMENT_PART}"),
    ("sentiment", r"\bsentiment\b(?:\s+score)?|\bpolarity\b"),
    ("api_calls", r"\b(?:API|call)\s+budget\b|\bAPI\s+calls?\b"),
    ("tokens", r"\btoken\s+(?:budget|cap|limit|ceiling)\b|\btokens?\b"),
    ("margin", r"(?<=%)\s*of\s+(?:revenue|sales)\b|(?<=percent)\s+of\s+(?:revenue|sales)\b"),
    ("gross_profit", r"\bgross\s+profits?\b"),
    ("net_income", r"\bnet\s+(?:income|profit|earnings)\b"),
    ("revenue", r"\brevenues?\b|\bsales\b|\btop[\s-]+line\b"),
    ("equity", r"\b(?:shareholders'?|stockholders'?)\s+equity\b|\bequity\b"),
    ("target", r"\bprice\s+targets?\b|\btarget\s+(?:price|of)\b|\bfair\s+value\b|\btarget(?=\s+[$\d])"),
    ("price", r"\bprices?\b|\bpriced\s+at\b|\btrad(?:es|ed|ing)\s+at\b|\bquoted\s+at\b|\bvalued\s+at\b"),
)
_CUES = tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _CUE_PATTERNS)

#: Count nouns right after a number (up to two modifiers between).
_COUNT_NOUNS: tuple[tuple[str, str], ...] = (
    ("volume", r"shares?"),
    ("sessions", r"sessions?|days"),
    ("news_count", r"headlines?|articles?|stories|news\s+items?|items?"),
    ("symbol_count", r"symbols?|stocks?|tickers?|names"),
    ("gaps", r"gaps?"),
    ("tokens", r"tokens?"),
    ("api_calls", r"(?:api\s+)?calls?"),
)
#: Words that may stand between a count and its noun ("2 pending sync gaps").
_COUNT_MODIFIERS = (
    r"pending|active|open|trading|tracked|stored|remaining|used|news|recent|daily|watchlist|unique|distinct|"
    r"returned|listed|vendor|api|sync|data|more|separate|individual"
)
_COUNT_NOUN = re.compile(
    rf"\s*(?:(?:{_COUNT_MODIFIERS})\s+){{0,2}}(?:"
    + "|".join(f"(?P<{name}>{pattern})" for name, pattern in _COUNT_NOUNS)
    + r")\b",
    re.IGNORECASE,
)
#: Letters glued to a number that name a field ("PE35").
_GLUED_FIELDS = {"pe": "pe", "p/e": "pe", "pb": "pb", "p/b": "pb", "ps": "ps", "p/s": "ps", "roe": "roe"}

#: Table labels that name a field exactly.
_LABEL_FIELDS: dict[str, str] = {
    **{key.replace("_", " "): name for key, name in _KEY_FIELDS.items()},
    **dict(_KEY_FIELDS),
    "adj close": "adjusted_close",
    "adj. close": "adjusted_close",
    "max drawdown": "drawdown",
    "drawdown": "drawdown",
    "volatility": "volatility",
    "p/e": "pe",
    "p/b": "pb",
    "p/s": "ps",
    "pe": "pe",
    "pb": "pb",
    "ps": "ps",
    "roe": "roe",
    "net margin": "net_margin",
    "gross margin": "gross_margin",
    "revenue growth": "revenue_growth",
    "target": "target",
    "price target": "target",
    "sentiment": "sentiment",
    "price": "price",
    "last price": "price",
}
_TIME_LABEL = re.compile(r"^(?:years?|dates?|period|as[\s-]+of|fiscal\s+year|fy|quarter|month)$", re.IGNORECASE)

_DECLINE = re.compile(
    r"\b(?:fell|fall|falls|falling|dropped|drop|drops|declined|decline|declines|down|lost|loss|slid|slumped|"
    r"plunged|sank|tumbled|shed)\b",
    re.IGNORECASE,
)
_RISE = re.compile(
    r"\b(?:rose|rise|rises|rising|gained|gain|gains|up|increased|increase|climbed|jumped|grew|"
    r"higher|advanced|rallied)\b",
    re.IGNORECASE,
)
_DECLINE_AFTER = re.compile(r"\s*(?:%|percent|pct)?\s*(?:decline|drop|fall|loss|drawdown)\b", re.IGNORECASE)
_CHANGE_CUE = re.compile(
    r"\b(?:up|down|rose|risen|fell|fallen|gained|lost|higher|lower|above|below|difference|change[ds]?|"
    r"increase[ds]?|decrease[ds]?|more\s+than|less\s+than|compared|spread|premium|discount)\b",
    re.IGNORECASE,
)

# ---- reasons (ADR-008 Am1 decision 9) -----------------------------------------

R_NOT_FOUND = "not found in this session's tool results"
R_OTHER_FIELD_V1 = "quoted for a different field than the tool returned"
R_TOOL_TEXT = "appears only in tool text; quote it to cite it"
R_QUOTE = "quoted text not found in the tool results"
R_PRECISE = "more precise than the evidence"
R_NO_TIME = "no matching tool date or time"
R_DERIVED = "derived value; only compute-tool results verify"


def _field_name(name: str | None) -> str:
    return FIELD_NAMES.get(name or "", name or "value")


# ---- evidence index ------------------------------------------------------------

_YEAR, _QUARTER, _MONTH, _DAY, _MINUTE, _SECOND, _SUB = 0, 1, 2, 3, 4, 5, 6


@dataclass(frozen=True)
class _Entry:
    value: float
    field: str
    subject: str | None
    unit: str
    currency: str | None
    derived: bool = False


@dataclass(frozen=True)
class _Instant:
    when: datetime
    level: int
    is_date: bool
    subject: str | None = None


@dataclass(frozen=True)
class _Window:
    subject: str | None
    start: date
    end: date


@dataclass
class Evidence:
    """The session ledger, typed: values, times, windows, free text (ADR-008 Am1).

    Implements: REQ-SI-INV-001 (ADR-008)
    """

    entries: list[_Entry] = field(default_factory=list)
    instants: list[_Instant] = field(default_factory=list)
    windows: list[_Window] = field(default_factory=list)
    free_text: list[str] = field(default_factory=list)
    free_digits: set[str] = field(default_factory=set)
    unavailable: set[tuple[str | None, str]] = field(default_factory=set)
    subjects: set[str] = field(default_factory=set)
    names: dict[str, str] = field(default_factory=dict)
    pool: set[str] = field(default_factory=set)
    floats: list[float] = field(default_factory=list)


_SYMBOL_SHAPE = re.compile(r"^(?:\d{1,5}\.[A-Za-z]{1,4}|[A-Za-z]{1,6}\.(?:US|HK))$")
_NUMERIC_STRING = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_ZONES = {"Z": 0, "UTC": 0, "GMT": 0, "HKT": 8 * 60, "EST": -5 * 60, "EDT": -4 * 60}
_ZONE_ALT = r"Z|UTC|GMT|HKT|EST|EDT|[+-]\d{2}:?\d{2}"
_EVIDENCE_DT = re.compile(
    rf"^(\d{{4}})-(\d{{2}})-(\d{{2}})(?:[T ](\d{{2}}):(\d{{2}})(?::(\d{{2}})(?:\.(\d{{1,9}}))?)?\s*({_ZONE_ALT})?)?$"
)
_EVIDENCE_STAMP = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(\d{1,9})?Z?$")


def _tool_of(key: str) -> str:
    match = re.search(r"([a-z_]+\.[a-z_.]+?)(?:#\d+)?$", key)
    return match.group(1) if match else key


def _subject_of(node: dict[str, Any]) -> str | None:
    for key in ("symbol", "canonical_symbol", "bucket"):
        value = node.get(key)
        if isinstance(value, str) and _SYMBOL_SHAPE.match(value.strip()):
            return value.strip().upper()
    return None


def _zone_minutes(zone: str | None) -> int:
    if not zone:
        return 0
    upper = zone.upper()
    if upper in _ZONES:
        return _ZONES[upper]
    sign = -1 if upper.startswith("-") else 1
    digits = upper[1:].replace(":", "")
    return sign * (int(digits[:2]) * 60 + int(digits[2:4]))


def _micros(frac: str | None) -> int:
    return int(frac[:6].ljust(6, "0")) if frac else 0


def _level(second: str | None, frac: str | None) -> int:
    if frac:
        return _SUB + len(frac)
    return _SECOND if second is not None else _MINUTE


def _parse_evidence_time(text: str) -> _Instant | None:
    text = text.strip()
    match = _EVIDENCE_DT.match(text)
    if match:
        year, month, day, hour, minute, second, frac, zone = match.groups()
    else:
        match = _EVIDENCE_STAMP.match(text)
        if not match:
            return None
        year, month, day, hour, minute, second, frac = match.groups()
        zone = "Z"
    try:
        if hour is None:
            return _Instant(datetime(int(year), int(month), int(day), tzinfo=timezone.utc), _DAY, True)
        moment = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second or 0), _micros(frac),
            tzinfo=timezone.utc,
        ) - timedelta(minutes=_zone_minutes(zone))
    except ValueError:
        return None
    return _Instant(moment, _level(second, frac), False)


def _parse_date(text: object) -> date | None:
    if not isinstance(text, str):
        return None
    instant = _parse_evidence_time(text)
    return instant.when.date() if instant is not None else None


def _norm_currency(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    upper = text.strip().upper().replace(" ", "")
    if upper in {"HKD", "HK$", "HKDOLLARS"}:
        return "HKD"
    if upper in {"USD", "US$"}:
        return "USD"
    if upper in {"RMB", "CNY", "CNH", "YUAN"}:
        return "CNY"
    if upper in {"EUR", "GBP", "JPY"}:
        return upper
    return None


def _normalize_quote(text: str) -> str:
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    text = text.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip().casefold()


def index_evidence(snapshot_values: object) -> Evidence:
    """Type the session ledger: values by subject, field and unit; times; free text.

    Implements: REQ-SI-INV-001 (ADR-008 Am1)
    """
    evidence = Evidence()
    if isinstance(snapshot_values, dict):
        for key, result in snapshot_values.items():
            tool = _tool_of(str(key))
            subject = _subject_of(result) if isinstance(result, dict) else None
            leaf_key = "" if isinstance(result, (dict, list, tuple)) else str(key)
            _walk(evidence, result, key=leaf_key, parent=str(key), siblings={}, tool=tool, subject=subject)
    else:
        _walk(evidence, snapshot_values, key="", parent="", siblings={}, tool="", subject=None)
    names: dict[str, set[str]] = {}
    _collect_names(snapshot_values, names)
    evidence.names = {word: next(iter(found)) for word, found in names.items() if len(found) == 1}
    for entry in evidence.entries:
        if not entry.derived:
            evidence.pool.add(v1._canon_number(entry.value))
            evidence.floats.append(entry.value)
    return evidence


def _collect_names(node: object, names: dict[str, set[str]]) -> None:
    if isinstance(node, dict):
        official = node.get("official_name")
        symbol = node.get("canonical_symbol") or node.get("symbol")
        if isinstance(official, str) and isinstance(symbol, str) and official.split():
            first = official.split()[0].strip(",.")
            if len(first) >= 3 and first[0].isupper() and first.lower() != "the":
                names.setdefault(first, set()).add(symbol.strip().upper())
        for value in node.values():
            _collect_names(value, names)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _collect_names(item, names)


def _evidence_field(key: str, parent: str, siblings: dict[str, Any], tool: str) -> str:
    lowered = key.lower()
    if lowered == "value":
        metric = siblings.get("metric")
        if isinstance(metric, str) and metric.lower() in _METRIC_FIELDS:
            return _METRIC_FIELDS[metric.lower()]
        return _METRIC_FIELDS.get(parent.lower(), "unknown")
    if lowered == "count":
        return "news_count" if tool.startswith("news.") else "unknown"
    if parent.lower() == "budget" and lowered in {"used", "remaining", "cap"}:
        return f"api_calls_{lowered}"
    if parent.lower() == "news" and lowered == "stored":
        return "news_count"
    if lowered in _INERT_KEYS:
        return "other"
    if lowered in _KEY_FIELDS:
        return _KEY_FIELDS[lowered]
    return _METRIC_FIELDS.get(lowered, "unknown")


def _count_field(key: str, tool: str) -> str | None:
    lowered = key.lower()
    if tool == "watchlist.list" and not lowered:
        return "symbol_count"
    if lowered == "items" and tool.startswith("news."):
        return "news_count"
    if lowered in {"pending_gaps", "no_data_gaps"}:
        return "gaps"
    return None


def _walk(
    evidence: Evidence, node: object, *, key: str, parent: str, siblings: dict[str, Any], tool: str,
    subject: str | None,
) -> None:
    if isinstance(node, dict):
        subject = _subject_of(node) or subject
        if subject:
            evidence.subjects.add(subject)
        _note_unavailable(evidence, node, key, subject)
        start, end = _parse_date(node.get("from")), _parse_date(node.get("until"))
        if start is not None and end is not None:
            evidence.windows.append(_Window(subject, min(start, end), max(start, end)))
        for child_key, value in node.items():
            _walk(evidence, value, key=str(child_key), parent=key or parent, siblings=node, tool=tool, subject=subject)
    elif isinstance(node, (list, tuple)):
        count_field = _count_field(key, tool)
        if count_field:
            evidence.entries.append(_Entry(float(len(node)), count_field, subject, "", None, derived=True))
        for item in node:
            _walk(evidence, item, key=key, parent=parent, siblings={}, tool=tool, subject=subject)
    elif isinstance(node, bool) or node is None:
        return
    elif isinstance(node, (int, float)):
        _add_entry(evidence, float(node), key, parent, siblings, tool, subject)
    elif isinstance(node, str):
        text = node.strip()
        if _NUMERIC_STRING.fullmatch(text):
            _add_entry(evidence, float(text.replace(",", "")), key, parent, siblings, tool, subject)
            return
        instant = _parse_evidence_time(text)
        if instant is not None:
            evidence.instants.append(replace(instant, subject=subject))
            return
        if re.search(r"[A-Za-z]", text):
            evidence.free_text.append(_normalize_quote(text))
            evidence.free_digits.update(v1._canon_token(token) for token in v1.extract_numbers(text))


def _add_entry(
    evidence: Evidence, value: float, key: str, parent: str, siblings: dict[str, Any], tool: str,
    subject: str | None,
) -> None:
    field_class = _evidence_field(key, parent, siblings, tool)
    unit = siblings.get("unit") if key.lower() == "value" else ""
    currency = _norm_currency(siblings.get("currency")) if field_class in _PRICE_FIELDS else None
    evidence.entries.append(_Entry(value, field_class, subject, unit if isinstance(unit, str) else "", currency))


def _note_unavailable(evidence: Evidence, node: dict[str, Any], key: str, subject: str | None) -> None:
    metric = node.get("metric")
    if "unavailable" in node:
        if isinstance(metric, str) and metric.lower() in _METRIC_FIELDS:
            evidence.unavailable.add((subject, _METRIC_FIELDS[metric.lower()]))
        elif key.lower() in _METRIC_FIELDS:
            evidence.unavailable.add((subject, _METRIC_FIELDS[key.lower()]))
    if key.lower() == "valuation" and any(isinstance(v, str) and "unavailable" in v for v in node.values()):
        evidence.unavailable.update((subject, name) for name in ("pe", "pb", "ps"))
    reason = node.get("stored_unavailable_reason")
    if isinstance(reason, str) and reason.strip():
        evidence.unavailable.update((subject, name) for name in ("revenue", "net_income", "gross_profit", "equity"))


# ---- answer structure ----------------------------------------------------------

_URL = re.compile(r"https?://\S+|\bwww\.\S+")
_MENTION = re.compile(r"(?<![\w.])(\d{1,5}\.[A-Z]{1,4}|[A-Z]{1,6}\.(?:US|HK))(?![\w])")


def _segments(text: str, boundary: re.Pattern[str]) -> list[tuple[int, int]]:
    spans, start = [], 0
    for match in boundary.finditer(text):
        spans.append((start, match.end()))
        start = match.end()
    spans.append((start, len(text)))
    return spans


def _containing(spans: list[tuple[int, int]], position: int) -> tuple[int, int]:
    for start, end in spans:
        if start <= position < end:
            return start, end
    return spans[-1]


def _table_cells(text: str) -> list[tuple[int, int, str, str]]:
    """(start, end, row label, column header) of every Markdown table cell."""
    cells: list[tuple[int, int, str, str]] = []
    header: list[str] | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        if not line.strip().startswith("|"):
            header = None
            offset += len(line)
            continue
        bars = [offset + index for index, char in enumerate(line) if char == "|"]
        spans = list(zip(bars, bars[1:]))
        values = [text[a + 1 : b].strip() for a, b in spans]
        if values and all(re.fullmatch(r":?-{2,}:?", value) for value in values if value):
            offset += len(line)
            continue
        if header is None:
            header = values
        for column, (a, b) in enumerate(spans):
            column_header = header[column] if column < len(header) else ""
            cells.append((a + 1, b, values[0] if values else "", column_header))
        offset += len(line)
    return cells


def _label(cell_text: str) -> str:
    return re.sub(r"[*_`]", "", cell_text).strip().lower()


class _Answer:
    """Positions of sentences, clauses, paragraphs, table cells, cues and subject mentions."""

    def __init__(self, text: str, evidence: Evidence) -> None:
        self.text = text
        self.evidence = evidence
        self.sentences = _segments(text, re.compile(r"[.!?](?=\s|$)|\n"))
        self.clauses = _segments(text, re.compile(r"[.!?](?=\s|$)|\n|;|,(?=\s)|\s[-–—]\s"))
        self.paragraphs = _segments(text, re.compile(r"\n\s*\n"))
        self.cells = _table_cells(text)
        cue_text = _URL.sub(lambda m: " " * len(m.group()), text)
        found = [(m.start(), m.end(), name) for name, pattern in _CUES for m in pattern.finditer(cue_text)]
        found.sort(key=lambda item: (item[0] - item[1], item[0]))
        self.cues: list[tuple[int, int, str]] = []
        for start, end, name in found:
            if all(end <= other[0] or start >= other[1] for other in self.cues):
                self.cues.append((start, end, name))
        self.cues.sort()
        self.mentions = sorted(set(self._mentions_in(text)))

    def _mentions_in(self, text: str, base: int = 0) -> list[tuple[int, int, str]]:
        found = [(base + m.start(), base + m.end(), m.group(1).upper()) for m in _MENTION.finditer(text)]
        for subject in self.evidence.subjects:
            code = subject.split(".")[0]
            if code.isdigit():
                pattern = rf"(?<![\w.,$]){re.escape(code)}(?![\w]|[.,]\d)"
                found.extend((base + m.start(), base + m.end(), subject) for m in re.finditer(pattern, text))
        for word, subject in self.evidence.names.items():
            name_pattern = rf"\b{re.escape(word)}\b"
            found.extend((base + m.start(), base + m.end(), subject) for m in re.finditer(name_pattern, text))
        return found

    def sentence(self, position: int) -> tuple[int, int]:
        """The sentence holding `position` (subject scope).

        Implements: REQ-SI-INV-001 (ADR-008)
        """
        return _containing(self.sentences, position)

    def clause(self, position: int) -> tuple[int, int]:
        """The clause holding `position` (field-cue scope).

        Implements: REQ-SI-INV-001 (ADR-008)
        """
        return _containing(self.clauses, position)

    def paragraph(self, position: int) -> tuple[int, int]:
        """The paragraph holding `position` (fallback subject scope).

        Implements: REQ-SI-INV-001 (ADR-008)
        """
        return _containing(self.paragraphs, position)

    def cell(self, position: int) -> tuple[str, str] | None:
        """(row label, column header) of the table cell holding `position`, if any.

        Implements: REQ-SI-INV-001 (ADR-008)
        """
        for start, end, row_label, column_header in self.cells:
            if start <= position < end:
                return row_label, column_header
        return None

    def label_subject(self, label: str) -> str | None:
        """The subject a table label names, if any.

        Implements: REQ-SI-INV-001 (ADR-008)
        """
        mentions = self._mentions_in(label)
        return mentions[0][2] if mentions else None


# ---- claim scanning ------------------------------------------------------------

_TIME_PART = rf"(\d{{1,2}}):(\d{{2}})(?::(\d{{2}})(?:\.(\d{{1,9}}))?)?(?:\s*({_ZONE_ALT})\b)?"
_STAMP = re.compile(r"(?<![\w])(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(\d{1,9})?Z?(?![\w])")
_ISO = re.compile(
    rf"(?<![\w.-])(\d{{4}})-(\d{{2}})-(\d{{2}})(?:(?:T|\s+|,\s*|\s+at\s+){_TIME_PART})?(?![\w-]|\.\d)"
)
_NATURAL_MDY = re.compile(
    rf"\b({v1._MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b(?:,?\s+(?:at\s+)?{_TIME_PART})?",
    re.IGNORECASE,
)
_NATURAL_DMY = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({v1._MONTH_ALT})\.?,?\s+(\d{{4}})\b(?:,?\s+(?:at\s+)?{_TIME_PART})?",
    re.IGNORECASE,
)
_QUARTER_YEAR = re.compile(r"\bQ([1-4])\s*(?:of\s+)?((?:19|20)\d{2})\b|\b((?:19|20)\d{2})\s*Q([1-4])\b")
_TIME_OF_DAY = re.compile(rf"(?<![\w:.]){_TIME_PART}(?![\w:])")
_COMPACT_DATE = re.compile(r"(?<![\w.,-])((?:19|20)\d{2})(\d{2})(\d{2})(?![\w.,%-]|\.\d)")
_TICKER = re.compile(r"(?<![\w.])\d{1,5}\.[A-Z]{1,4}(?![\w])")
_VERSION = re.compile(r"\bv\d+(?:\.\d+)+\b")
_QUOTE = re.compile(r'"([^"\n]{3,300})"|“([^”\n]{3,300})”')
_SUBJECT_VERB = re.compile(
    r"\s+(?:was|is|saw|brought|ended|began|started|marked|proved|remained|became|delivered|featured|"
    r"turned|looked|showed|has|had)\b",
    re.IGNORECASE,
)
_TIME_CUE = re.compile(
    r"\b(?:window|period|history|data|measured|measures|covers|covered|coverage|span|spans|spanning|"
    r"horizon|sample|series)\b",
    re.IGNORECASE,
)
_VALUE_CUE = re.compile(
    r"[%$]|\b(?:prices?|clos(?:e|ed|ing)|open(?:ed)?|traded|trades|rose|fell|gained|lost|climbed|dropped|"
    r"jumped|slid|values?|worth|cost|HKD|USD|RMB|CNY|yuan|dollars?|points?|shares?|percent)\b",
    re.IGNORECASE,
)
_WORD_UNITS = {
    word: index
    for index, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen".split()
    )
}
_WORD_TENS = {
    word: 10 * (index + 2)
    for index, word in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())
}
_WORD_SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
_NUMBER_WORD = "|".join(sorted([*_WORD_UNITS, *_WORD_TENS, "hundred"], key=len, reverse=True))
_WORD_UNIT = (
    r"percent|per\s+cent|basis\s+points|times|shares?|sessions?|trading\s+days|headlines?|articles?|stories|"
    r"news\s+items?|symbols?|stocks?|tickers?|gaps?|tokens?|api\s+calls?|calls?|dollars?|yuan|HKD|USD"
)
_WORD_PHRASE = re.compile(
    rf"\b((?:{_NUMBER_WORD})(?:[\s-]+(?:and\s+)?(?:{_NUMBER_WORD}))*)\b"
    rf"(?:\s+(thousand|million|billion|trillion)\b)?"
    rf"(?:(?:\s+(?:{_COUNT_MODIFIERS})){{0,2}}\s+({_WORD_UNIT})\b)?",
    re.IGNORECASE,
)


@dataclass
class _Pending:
    start: int
    end: int
    cls: str  # quantitative | temporal
    surface: str
    value: float = 0.0
    decimals: int = 0
    scale: float = 1.0
    words: bool = False
    unit_word: str = ""
    when: tuple[int, ...] = ()
    level: int = _DAY
    zone: str | None = None


@dataclass(frozen=True)
class ClaimVerdict:
    """One numeric claim of an answer and its verdict (ADR-008 Am1).

    `surface` is what records and notices show (a quantity without
    thousands separators, as v1 did; a time expression as written);
    `raw` is the exact text at [start, end). `kind` names the failure
    class of an unverified claim.

    Implements: REQ-SI-INV-001 (ADR-008)
    """

    surface: str
    raw: str
    start: int
    end: int
    cls: str
    verified: bool
    how: str = ""
    reason: str = ""
    kind: str = ""
    subject: str | None = None
    field: str | None = None


@dataclass(frozen=True)
class Scan:
    """Every claim and every exempt span of an answer.

    Implements: REQ-SI-INV-001 (ADR-008)
    """

    claims: list[ClaimVerdict]
    exempt: list[tuple[int, int, str]]


def _blank(work: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if work[index] != "\n":
            work[index] = " "


def _valid_date(year: int, month: int, day: int) -> bool:
    try:
        date(year, month, day)
    except ValueError:
        return False
    return 1900 <= year <= 2099


def _valid_time(hour: str, minute: str, second: str | None) -> bool:
    return int(hour) <= 23 and int(minute) <= 59 and int(second or 0) <= 59


def scan_claims(candidate: str, snapshot_values: object) -> Scan:
    """Classify and verify every number of an answer (ADR-008 Am1).

    Implements: REQ-SI-INV-001 (ADR-008)
    """
    evidence = index_evidence(snapshot_values)
    answer = _Answer(candidate, evidence)
    work = list(candidate)
    exempt: list[tuple[int, int, str]] = []
    pending: list[_Pending] = []

    def _current() -> str:
        return "".join(work)

    # 1. layout numbering and URLs
    for pattern in (v1._ENUM_MARKER, v1._HEADING_ORDINAL):
        for match in pattern.finditer(candidate):
            digits = re.search(r"\d+", match.group())
            if digits:
                start, end = match.start() + digits.start(), match.start() + digits.end()
                exempt.append((start, end, "layout"))
                _blank(work, start, end)
    for match in _URL.finditer(candidate):
        exempt.append((match.start(), match.end(), "identifier"))
        _blank(work, match.start(), match.end())

    # 2. whole temporal expressions
    _scan_times(_current, work, pending)

    # 3. partial dates and framed years (TP-020 frames), then the DE-13 rules
    for start, end, key in v1._calendar_references(_current()):
        level = _MONTH if len(key) == 6 else _YEAR
        when = (int(key[:4]), int(key[4:6])) if level == _MONTH else (int(key),)
        pending.append(_Pending(start, end, "temporal", candidate[start:end], when=when, level=level))
        _blank(work, start, end)
    _scan_de13_years(_current(), work, pending, answer)

    # 4. identifiers: the Am8 closed set, tickers (P4), versions
    for pattern in (v1._ID_CODE, _TICKER, _VERSION):
        for match in pattern.finditer(_current()):
            exempt.append((match.start(), match.end(), "identifier"))
            _blank(work, match.start(), match.end())

    # 5. number words with a unit (P5), then digit runs
    for match in _WORD_PHRASE.finditer(_current()):
        if not (match.group(2) or match.group(3)):
            continue
        value = _word_value(match.group(1))
        if value is None:
            continue
        scale = _WORD_SCALES[match.group(2).lower()] if match.group(2) else 1.0
        pending.append(
            _Pending(
                match.start(), match.end(), "quantitative", candidate[match.start() : match.end()],
                value=value, scale=scale, words=True, unit_word=(match.group(3) or "").lower(),
            )
        )
        _blank(work, match.start(), match.end())
    structural = v1._structural_tokens(snapshot_values)
    for match in v1._NUMBER_TOKEN.finditer(_current()):
        surface = match.group().replace(",", "")
        if surface in structural or v1._canon_token(surface) in structural:
            exempt.append((match.start(), match.end(), "code"))
            continue
        try:
            value = float(surface)
        except ValueError:
            continue
        decimals = len(surface.split(".", 1)[1]) if "." in surface else 0
        pending.append(_Pending(match.start(), match.end(), "quantitative", surface, value=value, decimals=decimals))

    pending.sort(key=lambda item: item.start)
    quotes = _quote_spans(candidate, evidence)
    typed = v1._typed_ohlcv_pool(snapshot_values)
    fields = _fields(answer, pending)
    verdicts = [_verify(item, answer, quotes, pending, typed, fields.get(id(item))) for item in pending]
    return Scan(claims=verdicts, exempt=sorted(exempt))


def _scan_times(_current: Callable[[], str], work: list[str], pending: list[_Pending]) -> None:
    def _add(match: re.Match[str], when: tuple[int, ...], level: int, zone: str | None = None) -> None:
        pending.append(
            _Pending(match.start(), match.end(), "temporal", match.group(), when=when, level=level, zone=zone)
        )
        _blank(work, match.start(), match.end())

    for match in _STAMP.finditer(_current()):
        year, month, day, hour, minute, second, frac = match.groups()
        if _valid_date(int(year), int(month), int(day)) and _valid_time(hour, minute, second):
            when = (int(year), int(month), int(day), int(hour), int(minute), int(second), _micros(frac))
            _add(match, when, _level(second, frac), "Z")
    for pattern, order in ((_ISO, "ymd"), (_NATURAL_MDY, "mdy"), (_NATURAL_DMY, "dmy")):
        for match in pattern.finditer(_current()):
            groups = match.groups()
            if order == "ymd":
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
            elif order == "mdy":
                year, month, day = int(groups[2]), v1._MONTHS[groups[0].lower()], int(groups[1])
            else:
                year, month, day = int(groups[2]), v1._MONTHS[groups[1].lower()], int(groups[0])
            if not _valid_date(year, month, day):
                continue
            hour, minute, second, frac, zone = groups[3:8]
            if hour is None or not _valid_time(hour, minute, second):
                if hour is not None:
                    continue
                _add(match, (year, month, day), _DAY)
                continue
            when = (year, month, day, int(hour), int(minute), int(second or 0), _micros(frac))
            _add(match, when, _level(second, frac), zone)
    for match in _QUARTER_YEAR.finditer(_current()):
        quarter = int(match.group(1) or match.group(4))
        year = int(match.group(2) or match.group(3))
        _add(match, (year, quarter), _QUARTER)
    for match in _TIME_OF_DAY.finditer(_current()):
        hour, minute, second, frac, zone = match.groups()
        if _valid_time(hour, minute, second):
            when = (-1, -1, -1, int(hour), int(minute), int(second or 0), _micros(frac))
            _add(match, when, _level(second, frac), zone)
    text = _current()
    for match in _COMPACT_DATE.finditer(text):
        year, month, day = (int(group) for group in match.groups())
        if not _valid_date(year, month, day):
            continue
        before = text[max(0, match.start() - 6) : match.start()]
        if re.search(r"(?:[$¥]|HKD|USD|RMB)\s?$", before) or v1._YEAR_VALUE_AFTER.match(text, match.end()):
            continue
        _add(match, (year, month, day), _DAY)


def _scan_de13_years(text: str, work: list[str], pending: list[_Pending], answer: _Answer) -> None:
    """DE-13: sentence-subject years, time-labelled table cells, time-cued ranges."""
    years = [m for m in v1._BARE_YEAR.finditer(text) if not v1._YEAR_VALUE_AFTER.match(text, m.end())]
    chosen: set[int] = set()
    for match in years:
        sentence_start, _sentence_end = answer.sentence(match.start())
        lead = text[sentence_start : match.start()]
        if re.fullmatch(r"[\s*_#>+\-]*", lead) and _SUBJECT_VERB.match(text, match.end()):
            chosen.add(match.start())
        cell = answer.cell(match.start())
        if cell is not None and (_TIME_LABEL.match(_label(cell[0])) or _TIME_LABEL.match(_label(cell[1]))):
            chosen.add(match.start())
    groups: list[list[re.Match[str]]] = []
    for match in years:
        if groups and v1._RANGE_LINK.fullmatch(text, groups[-1][-1].end(), match.start()):
            groups[-1].append(match)
        else:
            groups.append([match])
    for group in groups:
        if len(group) < 2:
            continue
        clause_start, clause_end = answer.clause(group[0].start())
        clause = text[clause_start:clause_end]
        if _TIME_CUE.search(clause) and not _VALUE_CUE.search(clause):
            chosen.update(match.start() for match in group)
    for match in years:
        if match.start() in chosen:
            year = match.group(1)
            pending.append(_Pending(match.start(), match.end(), "temporal", year, when=(int(year),), level=_YEAR))
            _blank(work, match.start(), match.end())


def _word_value(phrase: str) -> float | None:
    current = 0
    for word in re.split(r"[\s-]+", phrase.lower()):
        if word in {"", "and"}:
            continue
        if word in _WORD_UNITS:
            current += _WORD_UNITS[word]
        elif word in _WORD_TENS:
            current += _WORD_TENS[word]
        elif word == "hundred":
            current = (current or 1) * 100
        else:
            return None
    return float(current)


def _quote_spans(candidate: str, evidence: Evidence) -> list[tuple[int, int, bool]]:
    spans = []
    for match in _QUOTE.finditer(candidate):
        inner = match.group(1) or match.group(2) or ""
        if len(inner.split()) < 3:
            continue
        normalized = _normalize_quote(inner).strip(" .,;:!?")
        found = bool(normalized) and any(normalized in text for text in evidence.free_text)
        spans.append((match.start(), match.end(), found))
    return spans


# ---- verification -------------------------------------------------------------------


def _verify(
    item: _Pending, answer: _Answer, quotes: list[tuple[int, int, bool]], pending: list[_Pending],
    typed: dict[str, set[str]], field_name: str | None,
) -> ClaimVerdict:
    raw = answer.text[item.start : item.end]
    quote = next(((s, e, found) for s, e, found in quotes if s <= item.start and item.end <= e), None)
    if quote is not None and quote[2]:
        return ClaimVerdict(item.surface, raw, item.start, item.end, "quoted", True, "quoted")
    if item.cls == "temporal":
        verdict = _verify_time(item, raw, answer, pending)
    else:
        verdict = _verify_quantity(item, raw, answer, pending, typed, field_name)
    if quote is not None and not verdict.verified:
        return ClaimVerdict(
            verdict.surface, raw, item.start, item.end, verdict.cls, False, "", R_QUOTE, "quote",
            verdict.subject, verdict.field,
        )
    return verdict


def _resolve_subject(item: _Pending, answer: _Answer, pending: list[_Pending]) -> str | None:
    cell = answer.cell(item.start)
    if cell is not None:
        for label in (cell[1], cell[0]):
            subject = answer.label_subject(label)
            if subject:
                return subject
    s_start, s_end = answer.sentence(item.start)
    in_sentence = [m for m in answer.mentions if s_start <= m[0] < s_end]
    if "respectively" in answer.text[s_start:s_end].lower():
        quantities = [p for p in pending if p.cls == "quantitative" and s_start <= p.start < s_end]
        ordered = list(dict.fromkeys(subject for _start, _end, subject in in_sentence))
        if len(ordered) == len(quantities) and item in quantities:
            return ordered[quantities.index(item)]
    before = [m for m in in_sentence if m[1] <= item.start]
    if before:
        return before[-1][2]
    after = [m for m in in_sentence if m[0] >= item.end]
    if after:
        return after[0][2]
    p_start, _p_end = answer.paragraph(item.start)
    earlier = [m for m in answer.mentions if p_start <= m[0] and m[1] <= item.start]
    return earlier[-1][2] if earlier else None


_AFTER_SCALE = re.compile(r"(?:(k|m|mn|b|bn|tn)\b|\s+(thousand|million|billion|trillion|mn|bn|tn)\b)", re.IGNORECASE)
_AFTER_UNIT = re.compile(
    r"\s?(%|percent\b|per\s+cent\b|pct\b|percentage\s+points?\b|pp\b|bps\b|bp\b|basis\s+points?\b|x\b|times\b)",
    re.IGNORECASE,
)
_AFTER_CURRENCY = re.compile(r"\s+(HKD|USD|RMB|CNY|CNH|yuan)\b", re.IGNORECASE)
_SCALES = {
    "k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9,
    "tn": 1e12, "trillion": 1e12,
}


@dataclass(frozen=True)
class _Reading:
    value: float
    half: float
    scale: float
    unit: str  # "" | percent | bps | multiple
    currency: str | None
    sign: str  # "" | decline | rise
    after: str  # the text after the number, its scale, unit and currency


def _reading(item: _Pending, answer: _Answer) -> _Reading:
    full = answer.text
    rest = full[item.end : item.end + 80]
    scale, marker = item.scale, ""
    if item.words:
        marker = item.unit_word
    else:
        scale_match = _AFTER_SCALE.match(rest)
        if scale_match:
            scale = _SCALES[(scale_match.group(1) or scale_match.group(2)).lower()]
            rest = rest[scale_match.end() :]
        unit_match = _AFTER_UNIT.match(rest)
        if unit_match:
            marker = unit_match.group(1).lower()
            rest = rest[unit_match.end() :]
    if marker in {"%", "percent", "pct", "pp"} or marker.startswith(("per", "percentage")):
        unit = "percent"
    elif marker in {"bps", "bp"} or marker.startswith("basis"):
        unit = "bps"
    elif marker in {"x", "times"}:
        unit = "multiple"
    else:
        unit = ""
    currency_after = _AFTER_CURRENCY.match(rest)
    if currency_after:
        rest = rest[currency_after.end() :]
    before = full[max(0, item.start - 6) : item.start]
    currency_before = re.search(r"(HKD|USD|RMB|CNY|CNH|HK\$|US\$|\$|¥)\s?$", before, re.IGNORECASE)
    currency = None
    if currency_before:
        currency = _norm_currency(currency_before.group(1))
    elif currency_after:
        currency = _norm_currency(currency_after.group(1))
    sign = ""
    clause_start, _clause_end = answer.clause(item.start)
    words_before = re.findall(r"[A-Za-z']+", full[clause_start : item.start])[-4:]
    # after "to", "at" or "from" the number is a level, not a change
    if not words_before or words_before[-1].lower() not in {"to", "at", "from"}:
        window = " ".join(words_before)
        if _DECLINE.search(window):
            sign = "decline"
        elif _RISE.search(window):
            sign = "rise"
    if not sign and _DECLINE_AFTER.match(full, item.end):
        sign = "decline"
    return _Reading(item.value, 0.5 * 10 ** (-item.decimals), scale, unit, currency, sign, rest)


def _resolve_field(item: _Pending, answer: _Answer, reading: _Reading, pending: list[_Pending]) -> str | None:
    cell = answer.cell(item.start)
    if cell is not None:
        for label in (cell[0], cell[1]):
            name = _LABEL_FIELDS.get(_label(label))
            if name:
                return name
        for label in (cell[0], cell[1]):
            for name, pattern in _CUES:
                if pattern.search(label):
                    return name
    noun = _COUNT_NOUN.match(reading.after) if not item.words else _COUNT_NOUN.match(" " + item.unit_word)
    if noun:
        for name, _pattern in _COUNT_NOUNS:
            if noun.group(name):
                return name
    glued = re.search(r"([A-Za-z/]{2,3})$", answer.text[max(0, item.start - 3) : item.start])
    if glued and glued.group(1).lower() in _GLUED_FIELDS:
        return _GLUED_FIELDS[glued.group(1).lower()]
    if cell is not None:
        return None
    clause_start, clause_end = answer.clause(item.start)
    others = [
        p for p in pending if p is not item and p.cls == "quantitative" and clause_start <= p.start < clause_end
    ]
    best: tuple[int, int, str] | None = None
    for start, end, name in answer.cues:
        if start < clause_start or end > clause_end:
            continue
        if end <= item.start:
            # a cue before governs every number after it in the clause
            # ("closed at 75.6 and 644.63"), so another number may stand between
            rank = (item.start - end, 0)
        elif start >= item.end:
            # a cue after belongs to the nearest number before it, and does
            # not reach across a conjunction ("opened at 74.9 and closed")
            between = answer.text[item.end : start]
            if any(item.end <= p.start and p.end <= start for p in others) or _CONJUNCTION.search(between):
                continue
            rank = (start - item.end, 1)
        else:
            continue
        if best is None or rank < (best[0], best[1]):
            best = (rank[0], rank[1], name)
    return best[2] if best else None


#: A cue after the number does not reach across these.
_CONJUNCTION = re.compile(r"\b(?:and|while|but|whereas|before|after|then|with|against|versus|vs|plus)\b", re.IGNORECASE)
#: A number introduced as a comparison inherits the field it is compared with.
_COMPARISON = re.compile(
    r"(?:\b(?:down|up|lower|higher|compared)\s+(?:from|with|to)|\bagainst|\bversus|\bvs\.?|\bthan)"
    r"\s*(?:[$¥]|HKD|USD|RMB|CNY|HK\$|US\$)?\s*$",
    re.IGNORECASE,
)
_OF_TOTAL = re.compile(r"\b(?:out\s+)?of\s+(?:the\s+|a\s+|its\s+)?$", re.IGNORECASE)


def _refine(field_name: str, item: _Pending, answer: _Answer, pending: list[_Pending]) -> str:
    """Narrow a generic count (API calls) by the words around it."""
    rules = _REFINEMENTS.get(field_name)
    if not rules:
        return field_name
    clause_start, clause_end = answer.clause(item.start)
    if _OF_TOTAL.search(answer.text[clause_start : item.start]):
        return f"{field_name}_cap"
    quantities = [p for p in pending if p is not item and p.cls == "quantitative"]
    previous_end = max([p.end for p in quantities if clause_start <= p.end <= item.start], default=clause_start)
    next_start = min([p.start for p in quantities if item.end <= p.start < clause_end], default=clause_end)
    segment = answer.text[previous_end:next_start]
    for name, pattern in rules:
        if pattern.search(segment):
            return name
    return field_name


def _fields(answer: _Answer, pending: list[_Pending]) -> dict[int, str | None]:
    """The field of every quantitative claim, with comparison inheritance."""
    fields: dict[int, str | None] = {}
    for item in pending:
        if item.cls == "quantitative":
            name = _resolve_field(item, answer, _reading(item, answer), pending)
            fields[id(item)] = _refine(name, item, answer, pending) if name else None
    for item in pending:
        if item.cls != "quantitative" or fields[id(item)] is not None:
            continue
        sentence_start, _sentence_end = answer.sentence(item.start)
        if not _COMPARISON.search(answer.text[sentence_start : item.start]):
            continue
        earlier = [
            p for p in pending
            if p.cls == "quantitative" and sentence_start <= p.start < item.start and fields.get(id(p))
        ]
        if earlier:
            fields[id(item)] = fields[id(earlier[-1])]
    return fields


def _interpretations(reading: _Reading, entry: _Entry) -> list[float]:
    """Evidence value(s) expressed in the claim's written unit and scale."""
    values: list[float] = []
    fraction_like = entry.field in _FRACTION_FIELDS or entry.unit in {"fraction", "ratio"}
    if reading.unit == "percent":
        if fraction_like or entry.field == "unknown":
            values.append(entry.value * 100.0)
        if entry.field == "unknown" or entry.unit == "percent":
            values.append(entry.value)
    elif reading.unit == "bps":
        values.append(entry.value * 10000.0)
    else:
        values.append(entry.value)
    return [value / reading.scale for value in values]


def _close(left: float, right: float, half: float) -> bool:
    return abs(left - right) <= half + 1e-9 * max(1.0, abs(left), abs(right))


def _matches(reading: _Reading, entry: _Entry, field_name: str | None) -> tuple[bool, bool, str]:
    """(matched, exact, mismatch kind) of a reading against one evidence entry."""
    if reading.currency and entry.currency and reading.currency != entry.currency:
        return False, False, "currency"
    # a drawdown is a decline by definition: compared by magnitude, unless a
    # rise word claims the opposite direction
    magnitude = "drawdown" in (field_name, entry.field) and reading.sign != "rise"
    claimed = reading.value
    for candidate in _interpretations(reading, entry):
        target, value = candidate, claimed
        if magnitude:
            target, value = abs(candidate), abs(claimed)
        elif reading.sign == "decline" and claimed > 0:
            if candidate >= 0:
                if _close(candidate, claimed, reading.half):
                    return False, False, "rise"
                continue
            target = abs(candidate)
        elif reading.sign == "rise" and claimed > 0 and candidate < 0:
            if _close(abs(candidate), claimed, reading.half):
                return False, False, "decline"
            continue
        if _close(target, value, reading.half):
            return True, _close(target, value, 0.0), ""
    return False, False, ""


def _compatible(claimed: str, evidence_field: str) -> bool:
    if evidence_field == "unknown" or claimed == evidence_field:
        return True
    return evidence_field in _FAMILIES.get(claimed, frozenset())


def _verify_quantity(
    item: _Pending, raw: str, answer: _Answer, pending: list[_Pending], typed: dict[str, set[str]],
    field_name: str | None,
) -> ClaimVerdict:
    reading = _reading(item, answer)
    subject = _resolve_subject(item, answer, pending)
    evidence = answer.evidence

    def _verdict(verified: bool, how: str = "", reason: str = "", kind: str = "") -> ClaimVerdict:
        return ClaimVerdict(
            item.surface, raw, item.start, item.end, "quantitative", verified, how, reason, kind, subject, field_name
        )

    if field_name is None:
        return _verify_unfielded(item, reading, _verdict, answer, typed)
    in_scope = [
        entry for entry in evidence.entries
        if _compatible(field_name, entry.field) and (subject is None or entry.subject in (None, subject))
    ]
    mismatch = ""
    for entry in in_scope:
        matched, exact, kind = _matches(reading, entry, field_name)
        if matched:
            return _verdict(True, "exact" if exact else "rounded")
        mismatch = mismatch or kind
    label = _field_name(field_name)
    if not any(entry.field != "unknown" for entry in in_scope):
        owners = sorted(
            {
                s or "" for s, name in evidence.unavailable
                if name == field_name and (subject is None or s in (None, subject))
            }
        )
        if owners:
            owner = subject or owners[0]
            suffix = f" for {owner}" if owner else ""
            return _verdict(False, reason=f"the tool reported {label} unavailable{suffix}", kind="unavailable")
        return _verdict(
            False, reason=f"no {label} evidence" + (f" for {subject}" if subject else ""), kind="no_evidence"
        )
    for entry in evidence.entries:
        if (
            entry.field != "unknown" and _compatible(field_name, entry.field)
            and subject is not None and entry.subject not in (None, subject)
            and _matches(reading, entry, field_name)[0]
        ):
            return _verdict(False, reason=f"this {label} belongs to {entry.subject}", kind="subject_mismatch")
    for entry in evidence.entries:
        if (
            entry.field not in {"unknown", "other"} and not _compatible(field_name, entry.field)
            and (subject is None or entry.subject in (None, subject))
            and not entry.derived and _matches(reading, entry, entry.field)[0]
        ):
            other = _field_name(entry.field)
            return _verdict(False, reason=f"this is the {other}, not the {label}", kind="field_mismatch")
    if mismatch == "currency":
        currencies = ", ".join(sorted({e.currency for e in in_scope if e.currency}))
        return _verdict(False, reason=f"the tool reports {label} in {currencies}", kind="currency")
    if mismatch in {"rise", "decline"}:
        return _verdict(False, reason=f"the tool's {label} is a {mismatch}", kind="sign")
    clause_start, _clause_end = answer.clause(item.start)
    if _CHANGE_CUE.search(answer.text[clause_start : item.start]):
        return _verdict(False, reason=R_DERIVED, kind="derived")
    return _verdict(
        False, reason=f"differs from the tool's {label}" + (f" for {subject}" if subject else ""), kind="differs"
    )


def _verify_unfielded(
    item: _Pending, reading: _Reading, _verdict: Callable[..., ClaimVerdict], answer: _Answer,
    typed: dict[str, set[str]],
) -> ClaimVerdict:
    """The v1 rule, unchanged (P2): exact, BD-012 rounding, BD-015 percent, OHLCV field check."""
    evidence = answer.evidence
    if item.words:
        for entry in evidence.entries:
            if not entry.derived and _matches(reading, entry, None)[0]:
                return _verdict(True, "rounded")
        return _verdict(False, reason=R_NOT_FOUND, kind="not_found")
    token = item.surface
    canon = v1._canon_token(token)
    if canon in evidence.pool:
        stored = typed.get(canon)
        if stored and v1._field_mismatch(answer.text, token, stored):
            return _verdict(False, reason=R_OTHER_FIELD_V1, kind="field_mismatch")
        return _verdict(True, "exact")
    if any(v1._display_rounds_to(value, token) for value in evidence.floats):
        return _verdict(True, "rounded")
    if any(v1._display_percent_of(value, token, answer.text) for value in evidence.floats):
        return _verdict(True, "rounded")
    if canon in evidence.free_digits:
        return _verdict(False, reason=R_TOOL_TEXT, kind="tool_text")
    return _verdict(False, reason=R_NOT_FOUND, kind="not_found")


def _period(when: tuple[int, ...], level: int) -> tuple[date, date]:
    year = when[0]
    if level == _YEAR:
        return date(year, 1, 1), date(year, 12, 31)
    first_month = 3 * (when[1] - 1) + 1 if level == _QUARTER else when[1]
    months = 3 if level == _QUARTER else 1
    following = first_month + months
    end = date(year + (following > 12), (following - 1) % 12 + 1, 1) - timedelta(days=1)
    return date(year, first_month, 1), end


def _same_time(left: datetime, right: datetime, level: int, *, with_date: bool) -> bool:
    if with_date and left.date() != right.date():
        return False
    if (left.hour, left.minute) != (right.hour, right.minute):
        return False
    if level >= _SECOND and left.second != right.second:
        return False
    if level > _SUB:
        digits = level - _SUB
        return f"{left.microsecond:06d}"[:digits] == f"{right.microsecond:06d}"[:digits]
    return True


def _verify_time(item: _Pending, raw: str, answer: _Answer, pending: list[_Pending]) -> ClaimVerdict:
    subject = _resolve_subject(item, answer, pending)
    evidence = answer.evidence

    def _verdict(verified: bool, how: str = "", reason: str = "", kind: str = "") -> ClaimVerdict:
        return ClaimVerdict(item.surface, raw, item.start, item.end, "temporal", verified, how, reason, kind, subject)

    if item.level in (_YEAR, _QUARTER, _MONTH):
        first, last = _period(item.when, item.level)
        if any(first <= instant.when.date() <= last for instant in evidence.instants):
            return _verdict(True, "calendar")
        windows = [w for w in evidence.windows if subject is None or w.subject in (None, subject)]
        if any(first <= window.end and last >= window.start for window in windows):
            return _verdict(True, "window")
        return _verdict(False, reason=R_NO_TIME, kind="no_time")
    # days and times are checked against the dates of the claim's subject
    # first (ADR-008 decision 2: evidence is indexed by symbol and date)
    own = [i for i in evidence.instants if subject is None or i.subject in (None, subject)]
    foreign = [i for i in evidence.instants if i not in own]
    if item.level == _DAY:
        day = date(*item.when[:3])
        if any(instant.when.date() == day for instant in own):
            return _verdict(True, "exact")
        owner = next((i.subject for i in foreign if i.when.date() == day), None)
        if owner:
            return _verdict(False, reason=f"this date belongs to {owner}", kind="subject_mismatch")
        return _verdict(False, reason=R_NO_TIME, kind="no_time")
    claim_day: date | None = None if item.when[0] < 0 else date(*item.when[:3])
    if claim_day is None:
        sentence = answer.sentence(item.start)
        same = [p for p in pending if p.level == _DAY and p.cls == "temporal" and answer.sentence(p.start) == sentence]
        if same:
            claim_day = date(*same[0].when[:3])
    hour, minute, second, micros = item.when[3:7]
    anchor = claim_day or date(2000, 1, 1)
    moment = datetime(anchor.year, anchor.month, anchor.day, hour, minute, second, micros, tzinfo=timezone.utc)
    moment -= timedelta(minutes=_zone_minutes(item.zone))
    precise = False
    owner = None
    for instant in [*own, *foreign]:
        if instant.is_date:
            if claim_day is not None and instant.when.date() == moment.date() and instant in own:
                precise = True
            continue
        if _same_time(moment, instant.when, min(item.level, instant.level), with_date=claim_day is not None):
            if instant not in own:
                owner = owner or instant.subject
            elif item.level <= instant.level:
                return _verdict(True, "exact")
            else:
                precise = True
    if precise:
        return _verdict(False, reason=R_PRECISE, kind="precise")
    if owner:
        return _verdict(False, reason=f"this time belongs to {owner}", kind="subject_mismatch")
    return _verdict(False, reason=R_NO_TIME, kind="no_time")


# ---- the post-check result -----------------------------------------------------------


def check(candidate: str, snapshot_values: object) -> v1.NumberCheck:
    """The INV-001 verdict over typed claims, in the v1 NumberCheck shape.

    Implements: REQ-SI-INV-001 (ADR-008)
    """
    scan = scan_claims(candidate, snapshot_values)
    matched: list[str] = []
    rounded: list[str] = []
    failed: list[str] = []
    calendar: list[str] = []
    field_mismatch: list[str] = []
    subject_mismatch: list[str] = []
    for claim in scan.claims:
        if claim.verified:
            if claim.how in {"calendar", "window"}:
                calendar.append(claim.raw)
            elif claim.how == "rounded":
                rounded.append(claim.surface)
            else:
                matched.append(claim.surface)
            continue
        failed.append(claim.surface)
        if claim.kind == "field_mismatch":
            field_mismatch.append(claim.surface)
        elif claim.kind == "subject_mismatch":
            subject_mismatch.append(claim.surface)
    structural = [candidate[start:end].replace(",", "") for start, end, kind in scan.exempt if kind == "code"]
    return v1.NumberCheck(
        passed=not failed,
        matched=matched,
        failed=failed,
        rounded=rounded,
        structural=structural,
        field_mismatch=field_mismatch,
        calendar=calendar,
        checked_text=candidate,
        subject_mismatch=subject_mismatch,
        claims=list(scan.claims),
    )
