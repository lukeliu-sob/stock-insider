"""Runtime guardrail: INV-001 numeric post-check and INV-002 epistemic filter.

Semantics follow docs/architecture/invariants.md exactly. Since
ADR-008 (TP-023), a number the post-check cannot verify is displayed
and stored only with the unverified marker and named in a notice; the
response is withheld only when such a number cannot be located for
marking (fail-closed) or the language policy fails. Epistemic
violations strip and regenerate once, then refuse with a
hypothesis-labeled summary. This module is the authoritative, fully
testable verdict library; the agent loop wires it into the pipeline.

Number matching is exact-after-normalization (no tolerance: a ±1
mismatch fails), and derived numbers are NOT accepted unless a compute
tool registered them in the snapshot — precision over convenience
(ADR-006).

Implements: REQ-SI-INV-001, REQ-SI-INV-002, REQ-SI-INV-003 (ADR-006, ADR-008)
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from stockinsider.shared.language import is_english_only

# ---- INV-001: numeric provenance post-check ---------------------------------

_NUMBER_TOKEN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

#: Identifier codes are references, not numerics (TP-018b): the
#: extractor used to mine "-005" out of "ADR-005" and quarantine a
#: sentence for quoting the product's own rule IDs back at the user.
#: Fifth-audit correction (TP-019, ADR-006 Am8): the TP-018b form
#: blanked ANY short letter run glued to digits, so "closed at
#: HKD777", "USD1200", "PE35" and "YTD-12%" escaped INV-001 entirely.
#: Only the closed set of reference shapes below is blanked: the
#: product's governance IDs, period labels, prompt versions and
#: benchmark names whose digits are part of the name. Everything else
#: glued to letters is extracted and checked like any other numeric.
_ID_CODE = re.compile(
    r"\bREQ-SI-[A-Z]{2,4}-\d{3}\b"
    r"|\b(?:GOV|ADR|TP|INV|BD|RM|PR|FR|QA|PERF|COST|SEC|AILOG)-\d{1,4}[a-z]?\b"
    r"|\bAm\d{1,2}\b|\bQ[1-4]\b|\bH[12]\b|\bFY\d{2}(?:\d{2})?\b|\bv\d{1,2}\b"
    r"|\bS&P\s?(?:400|500|600)\b|\bSP500\b|\bNasdaq[- ]100\b|\bCOVID-19\b",
    re.IGNORECASE,
)

#: Line-leading enumeration markers ("1. ", "12) ") are document
#: structure, not cited numerics (BD-016). A marker is at most three
#: digits followed by a period/paren and whitespace; genuine values
#: keep their decimals ("24879.2402" does not match) and four-digit
#: years at line start are untouched.
_ENUM_MARKER = re.compile(r"(?m)^\s{0,8}\d{1,3}[.)]\s")


#: new-5 (TP-018, ADR-006 Am6) + fourth-audit tightening (TP-018b):
#: only a PUNCTUATED 1-2 digit ordinal ("## 12. Data") or a single
#: bare digit ("## 6 Summary") is layout. An unpunctuated leading
#: heading number of two digits or more ("## 85 USD price target")
#: is a numeric claim and is checked like any other.
_HEADING_ORDINAL = re.compile(r"(?m)^#{1,6}\s+(?:\d{1,2}[.)]|\d)\s+")

_SYMBOLISH = re.compile(r"\b(\d{1,5})\.[A-Za-z]{2,5}\b")


def _strip_enumeration(text: str) -> str:
    """Remove layout numbering: line-leading markers and heading ordinals.

    Implements: REQ-SI-INV-001 (ADR-006, BD-016 amendment; TP-018 ADR-006 Am6)
    """
    return _HEADING_ORDINAL.sub("", _ENUM_MARKER.sub("", text))


def _structural_tokens(snapshot_values: object) -> set[str]:
    """Digit fragments of symbol-shaped strings present in the pool.

    A pool string like 0700.HK (symbol fields, bucket names) makes the
    token 0700 a STRUCTURAL reference, not a numeric claim: citing a
    stock code is identification, not data. Only fragments of symbols
    actually present in this session's evidence pass - a random 0700
    with no such symbol in the pool still fails. Counts and prose
    numbers are deliberately NOT covered (owner-approved direction,
    TP-017 PR-3a; the standing extraction-semantics decision).

    Implements: REQ-SI-INV-001 (ADR-006; TP-017 PR-3a)
    """
    out: set[str] = set()
    _collect_symbol_fragments(snapshot_values, out)
    return out


def _collect_symbol_fragments(node: object, out: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                out.update(m.group(1) for m in _SYMBOLISH.finditer(key))
            _collect_symbol_fragments(value, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _collect_symbol_fragments(item, out)
    elif isinstance(node, str):
        out.update(m.group(1) for m in _SYMBOLISH.finditer(node))


#: ISO calendar dates in responses (2026-09-23) normalize to the
#: compact form the pool already carries (20260923, from GDELT-style
#: seendates). Without this, the extractor reads the hyphenated form
#: as a year plus orphaned month/day fragments (-09, -23) that match
#: nothing (BD-018).
_ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


#: Fifth-audit extension of BD-018 (TP-019, ADR-006 Am8): a natural-
#: language calendar date ("September 23, 2026", "23 Sep 2026") folds
#: to the same compact form, so a correctly cited date no longer
#: quarantines a whole answer as the orphans "23" and "2026". A date
#: absent from the pool still fails: only the rendering is normalized.
_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
            ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
            ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_DAY_YEAR = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE
)
_DAY_MONTH_YEAR = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})\.?,?\s+(\d{{4}})\b", re.IGNORECASE
)


def _compact_date(year: str, month: int, day: str) -> str | None:
    if not 1 <= int(day) <= 31:
        return None
    return f"{year}{month:02d}{int(day):02d}"


def _fold_month_day_year(match: re.Match[str]) -> str:
    folded = _compact_date(match.group(3), _MONTHS[match.group(1).lower()], match.group(2))
    return folded if folded is not None else match.group(0)


def _fold_day_month_year(match: re.Match[str]) -> str:
    folded = _compact_date(match.group(3), _MONTHS[match.group(2).lower()], match.group(1))
    return folded if folded is not None else match.group(0)


def _normalize_dates(text: str) -> str:
    """Fold ISO and natural-language calendar dates into the pool's compact form.

    Implements: REQ-SI-INV-001 (ADR-006, BD-018 amendment; TP-019)
    """
    text = _MONTH_DAY_YEAR.sub(_fold_month_day_year, text)
    text = _DAY_MONTH_YEAR.sub(_fold_day_month_year, text)
    return _ISO_DATE.sub(r"\1\2\3", text)


#: TP-020 (ADR-006 Am9, BD-026): partial dates. A live BYD turn was
#: quarantined as "data unavailable for: 2025": the model wrote the
#: volatility window's start at month precision ("since September
#: 2025"), and the evidence carries dates only as full dates
#: (20250925), never as a bare 2025. A month-year or a bare year
#: written as a time reference is now checked at the precision it is
#: written: it passes when a date in the evidence falls in that month
#: or year, and only then leaves the numeric check. A reference the
#: evidence does not support stays in the text and fails there exactly
#: as before. Full dates fold first, so "26 September 2025" keeps its
#: day precision.
_YEAR = r"(?:19|20)\d{2}"
_MONTH_YEAR = re.compile(rf"\b({_MONTH_ALT})\.?,?\s+({_YEAR})(?!\d|[.,]\d)", re.IGNORECASE)
_ISO_YEAR_MONTH = re.compile(rf"(?<![\w.,-])({_YEAR})-(0[1-9]|1[0-2])(?![\w%-]|[.,]\d)")
_COMPACT_STAMP = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})T\d{2}")

#: A bare four-digit number is a year only inside a temporal frame: a
#: cue right before it ("in", "since", "late", "mid-", "end of", "Q4"),
#: a cue right after it ("'s", "peak", "high", "results", "Q4"), or a
#: range link to a framed year or a month-year ("late 2025 to 2026").
#: Value frames never qualify - "closed at 2026", "2026 shares",
#: "HKD2026", "2026%", the ticker code "2020.HK", a bare table cell -
#: and a value word after any member of a range cancels the range.
#: Fail-closed: a frame not listed here leaves the number a numeric
#: claim, since pool membership alone would let any fabricated value
#: equal to an evidence year pass (the BD-020 class).
_BARE_YEAR = re.compile(rf"(?<![\w$.,£¥€])({_YEAR})(?![\w%]|[.,]\d|\.[A-Za-z])")
_YEAR_CUE_BEFORE = re.compile(
    r"\b(?:in|since|during|throughout|until|till|before|after|early|mid|late|"
    r"(?:end|start|beginning|middle|rest|half)\s+of|as\s+of|the\s+year|year-end|"
    r"fiscal|calendar|full[- ]year|FY|Q[1-4]|H[12]|spring|summer|autumn|winter)"
    r"(?:\s+|\s*-\s*)\Z",
    re.IGNORECASE,
)
_YEAR_CUE_AFTER = re.compile(
    r"['’]s\b|(?:\s+|\s*-\s*)(?:Q[1-4]|H[12]|peaks?|troughs?|highs?|lows?|levels?|"
    r"window|period|results|report|annual|interim|earnings|guidance|year-end|full[- ]year)\b",
    re.IGNORECASE,
)
_YEAR_VALUE_AFTER = re.compile(
    r"\s*(?:%|percent\b|pct\b|bps?\b|x\b|times\b|k\b|mn\b|bn\b|thousand\b|million\b|"
    r"billion\b|trillion\b|shares\b|units\b|points?\b|pts\b|dollars?\b|yuan\b|"
    r"HKD\b|USD\b|RMB\b|CNY\b|CNH\b|EUR\b|GBP\b|JPY\b)",
    re.IGNORECASE,
)
_RANGE_LINK = re.compile(r"\s*(?:-|–|—|/|&|to|through|thru|and)\s*", re.IGNORECASE)


def _dates_in(text: str) -> list[tuple[str, int]]:
    """(year, month) of every date-shaped run in an evidence string.

    Implements: REQ-SI-INV-001 (ADR-006 Am9; TP-020)
    """
    found: list[tuple[str, int]] = []
    for pattern in (_ISO_DATE, _COMPACT_STAMP):
        for match in pattern.finditer(text):
            if 1 <= int(match.group(2)) <= 12 and 1 <= int(match.group(3)) <= 31:
                found.append((match.group(1), int(match.group(2))))
    for match in _MONTH_DAY_YEAR.finditer(text):
        month = _MONTHS[match.group(1).lower()]
        if _compact_date(match.group(3), month, match.group(2)) is not None:
            found.append((match.group(3), month))
    for match in _DAY_MONTH_YEAR.finditer(text):
        month = _MONTHS[match.group(2).lower()]
        if _compact_date(match.group(3), month, match.group(1)) is not None:
            found.append((match.group(3), month))
    found.extend((match.group(2), _MONTHS[match.group(1).lower()]) for match in _MONTH_YEAR.finditer(text))
    found.extend((match.group(1), int(match.group(2))) for match in _ISO_YEAR_MONTH.finditer(text))
    return found


def _evidence_calendar(snapshot_values: object) -> set[str]:
    """Calendar keys (YYYY and YYYYMM) of every date the evidence carries.

    Only date-shaped strings count, never a bare number: a volume of
    202509 makes no month citable.

    Implements: REQ-SI-INV-001 (ADR-006 Am9; TP-020)
    """
    keys: set[str] = set()

    def _sink(value: object) -> None:
        if isinstance(value, str):
            for year, month in _dates_in(value):
                keys.update((year, f"{year}{month:02d}"))

    _walk(snapshot_values, _sink)
    return keys


def _calendar_references(text: str) -> list[tuple[int, int, str]]:
    """Partial-date references in a response: (start, end, calendar key).

    Month-years key as YYYYMM, framed bare years as YYYY. Runs on text
    whose full dates are already folded (_normalize_dates).

    Implements: REQ-SI-INV-001 (ADR-006 Am9; TP-020)
    """
    months = [
        (match.start(), match.end(), f"{match.group(2)}{_MONTHS[match.group(1).lower()]:02d}")
        for match in _MONTH_YEAR.finditer(text)
    ]
    months.extend(
        (match.start(), match.end(), match.group(1) + match.group(2)) for match in _ISO_YEAR_MONTH.finditer(text)
    )
    # (start, end, key, frame): True framed, False unframed, None value frame
    items: list[tuple[int, int, str, bool | None]] = [(start, end, key, True) for start, end, key in months]
    for match in _BARE_YEAR.finditer(text):
        if any(start <= match.start() < end for start, end, _key in months):
            continue  # the year of a month-year is checked at month precision
        frame: bool | None = None
        if not _YEAR_VALUE_AFTER.match(text, match.end()):
            frame = bool(
                _YEAR_CUE_BEFORE.search(text, max(0, match.start() - 32), match.start())
                or _YEAR_CUE_AFTER.match(text, match.end())
            )
        items.append((match.start(), match.end(), match.group(1), frame))
    groups: list[list[tuple[int, int, str, bool | None]]] = []
    for item in sorted(items):
        if groups and _RANGE_LINK.fullmatch(text, groups[-1][-1][1], item[0]):
            groups[-1].append(item)
        else:
            groups.append([item])
    refs = list(months)
    for group in groups:
        frames = [frame for _start, _end, _key, frame in group]
        if None not in frames and any(frames):
            # month-year members are already in refs; add the bare years
            refs.extend((start, end, key) for start, end, key, _frame in group if len(key) == 4)
    return refs


def _strip_verified_calendar(text: str, evidence: set[str]) -> tuple[str, list[str]]:
    """Blank the partial-date references the evidence calendar supports.

    A verified reference leaves the numeric check and is listed for
    audit; an unsupported one stays in the text and is checked - and
    fails - like any other numeric. Blanking keeps offsets stable.

    Implements: REQ-SI-INV-001 (ADR-006 Am9; TP-020)
    """
    verified = sorted((start, end) for start, end, key in _calendar_references(text) if key in evidence)
    if not verified:
        return text, []
    chars = list(text)
    for start, end in verified:
        chars[start:end] = " " * (end - start)
    return "".join(chars), [text[start:end] for start, end in verified]


#: M2 phase 1 (TP-018, ADR-006 Am6): typed numeric provenance for the
#: OHLCV field class. A pool hit used to pass regardless of WHICH
#: field the sentence claimed - quoting the open as the close passed
#: INV-001. The typed pool maps each canonical value to the set of
#: OHLCV field names it is actually stored under; a token whose
#: sentence context names a field the value is NOT stored under
#: fails the check. Phase-2 (non-OHLCV semantics) is future work.
_OHLCV_CANON = {
    "open": "open", "opens": "open", "opened": "open", "opening": "open",
    "open_price": "open", "day_open": "open",
    "high": "high", "highs": "high", "day_high": "high",
    "low": "low", "lows": "low", "day_low": "low",
    "close": "close", "closes": "close", "closed": "close",
    "closing": "close", "closings": "close",
    "close_price": "close", "last_close": "close", "prev_close": "close",
    "previous_close": "close", "adj_close": "adjusted_close",
    "adjusted": "adjusted_close", "adjusted_close": "adjusted_close",
    # no "vol" alias (TP-019): in market prose "vol" abbreviates
    # volatility, and mapping it to volume mis-typed nearby prices
    "volume": "volume", "volumes": "volume",
}

#: Fourth-audit fix (TP-018b): field mentions tokenize as identifiers
#: so snake_case names ("adjusted_close" in a model-authored table
#: row) resolve to their field - the word-boundary alternation used
#: to see nothing inside "adjusted_close" and then mis-attribute the
#: value to the "close" word two rows up.
_FIELD_TOKEN = re.compile("[A-Za-z_]+")


def _mentioned_fields(window: str) -> "set[str]":
    """OHLCV fields named (directly or by alias) inside a word window."""
    return {
        _OHLCV_CANON[token.lower()]
        for token in _FIELD_TOKEN.findall(window)
        if token.lower() in _OHLCV_CANON
    }




def _typed_ohlcv_pool(snapshot_values: object) -> dict[str, set[str]]:
    """Canonical value -> OHLCV field names it is stored under.

    Only direct OHLCV-key -> numeric-leaf pairs register (the
    product's bar payloads are flat); nothing is guessed.

    Implements: REQ-SI-INV-001 (ADR-006 Am6; TP-018 PR-3)
    """
    out: dict[str, set[str]] = {}

    def _visit(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                canon_key = _OHLCV_CANON.get(str(key).lower())
                if (
                    canon_key
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                ):
                    out.setdefault(_canon_number(value), set()).add(canon_key)
                else:
                    _visit(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                _visit(item)

    _visit(snapshot_values)
    return out


def _field_mismatch(stripped_text: str, token: str, stored_fields: set[str]) -> bool:
    """True when field-mentioning occurrences of token all disagree.

    An occurrence is CONSISTENT when its word window mentions at
    least one field the value is stored under (a doji's open ==
    close passes); INCONSISTENT when it mentions only other
    OHLCV fields. The token fails only when some occurrence is
    inconsistent and none is consistent.

    Implements: REQ-SI-INV-001 (ADR-006 Am6; TP-018 PR-3)
    """
    consistent = False
    inconsistent = False
    for match in re.finditer(re.escape(token), stripped_text):
        window = stripped_text[max(0, match.start() - 48): match.end() + 48]
        mentioned = _mentioned_fields(window)
        if not mentioned:
            continue
        if mentioned & stored_fields:
            consistent = True
        else:
            inconsistent = True
    return inconsistent and not consistent


def _canon_number(value: float | int) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _canon_token(token: str) -> str:
    try:
        return _canon_number(float(token))
    except ValueError:
        return token


def extract_numbers(text: str) -> list[str]:
    """Extract normalized numeric tokens (thousands separators stripped).

    Identifier codes are blanked first (TP-018b), but only the closed
    reference set in ``_ID_CODE`` (TP-019): digits glued to any other
    letters ("HKD777", "PE35") are extracted and checked.

    Implements: REQ-SI-INV-001 (ADR-006; TP-019)
    """
    return [
        token.replace(",", "")
        for token in _NUMBER_TOKEN.findall(_ID_CODE.sub(" ", text))
    ]


def _walk(node: object, sink: Callable[[object], None]) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _walk(value, sink)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _walk(value, sink)
    else:
        sink(node)


def _values_pool(snapshot_values: object) -> set[str]:
    pool: set[str] = set()

    def _sink(value: object) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            pool.add(_canon_number(value))
        elif isinstance(value, str):
            for token in extract_numbers(_normalize_dates(value)):
                pool.add(_canon_token(token))

    _walk(snapshot_values, _sink)
    return pool


def _pool_floats(snapshot_values: object) -> list[float]:
    """Numeric leaf values as floats (display-rounding match candidates).

    Implements: REQ-SI-INV-001 (ADR-006, BD-012 amendment)
    """
    floats: list[float] = []

    def _sink(value: object) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            floats.append(float(value))
        elif isinstance(value, str):
            for token in extract_numbers(_normalize_dates(value)):
                try:
                    floats.append(float(token))
                except ValueError:
                    continue

    _walk(snapshot_values, _sink)
    return floats


#: Display-rounding tolerance: a token with exactly d decimals (d in 2..4)
#: matches a pool value within half an ulp of that decimal place. This is a
#: rendering convention, not a numeric tolerance: integer-scale deviations
#: (the ±1 adversarial class) still fail — tokens with 0 or 1 decimals never
#: display-round-match, and the bound shrinks with d (BD-012).
_DISPLAY_DECIMALS = (2, 3, 4)


#: Percent-display conversion: a token that equals a pool value
#: multiplied by 100 (2-4 decimals) matches only when a percent
#: marker is adjacent in the response text (BD-015). Bare numbers
#: never qualify; the marker requirement keeps integer-scale
#: adversarial classes failing exactly as before.
_PERCENT_MARKER = re.compile(r"%(?!\d)|\bpercent\b|\bpct\b", re.IGNORECASE)


def _percent_marker_adjacent(candidate: str, token: str) -> bool:
    """True when some occurrence of ``token`` sits next to a percent marker."""
    search_from = 0
    while True:
        index = candidate.find(token, search_from)
        if index < 0:
            return False
        window = candidate[max(0, index - 12): index + len(token) + 12]
        if _PERCENT_MARKER.search(window):
            # exclude the token itself being part of a longer number
            return True
        search_from = index + len(token)


def _display_percent_of(value: float, token: str, candidate: str) -> bool:
    """True when token is the percent rendering of a fractional value.

    Implements: REQ-SI-INV-001 (ADR-006, BD-015 amendment)
    """
    decimals = _token_decimals(token)
    if decimals not in (1, 2, 3, 4):
        return False
    try:
        rendered = float(token)
    except ValueError:
        return False
    if abs(value * 100.0 - rendered) > 0.5 * 10**-decimals + 1e-9:
        return False
    return _percent_marker_adjacent(candidate, token)


def _token_decimals(token: str) -> int | None:
    if "." not in token:
        return 0
    return len(token.split(".", 1)[1]) or None


def _display_rounds_to(value: float, token: str) -> bool:
    """True when token is a standard decimal rendering of value.

    Implements: REQ-SI-INV-001 (ADR-006, BD-012 amendment)
    """
    decimals = _token_decimals(token)
    if decimals not in _DISPLAY_DECIMALS:
        return False
    try:
        rendered = float(token)
    except ValueError:
        return False
    return abs(value - rendered) <= 0.5 * 10**-decimals + 1e-12


@dataclass(frozen=True)
class NumberCheck:
    """INV-001 verdict: matched and failed numeric tokens.

    Implements: REQ-SI-INV-001 (ADR-006)
    """

    passed: bool
    matched: list[str]
    failed: list[str]
    rounded: list[str] = field(default_factory=list)
    structural: list[str] = field(default_factory=list)
    field_mismatch: list[str] = field(default_factory=list)
    #: partial dates verified against the evidence calendar (TP-020)
    calendar: list[str] = field(default_factory=list)
    #: the text the tokens were extracted from (after layout stripping and
    #: date folding): the fail-closed marking check compares against it (ADR-008)
    checked_text: str = ""
    #: numbers attributed to the wrong subject (ADR-008 Am1, DE-12)
    subject_mismatch: list[str] = field(default_factory=list)
    #: every numeric claim with its position and verdict (ADR-008 Am1)
    claims: list[Any] = field(default_factory=list)


def postcheck_numbers(candidate: str, snapshot_values: object) -> NumberCheck:
    """Verify every numeric claim of an answer against the session ledger.

    ADR-008 Amendment 1 (TP-024): numbers are typed claims. A claim with
    a field cue is compared with evidence of its subject and field at
    its written precision; one without keeps the v1 rule below (exact
    after normalization, 2-4-decimal display rounding as `rounded`,
    BD-012; marker-gated percents, BD-015); times are parsed whole;
    partial dates are checked at their written precision and audited
    as `calendar` (TP-020).

    Implements: REQ-SI-INV-001 (ADR-006, ADR-008)
    """
    from stockinsider.agent import guardrail_claims

    return guardrail_claims.check(candidate, snapshot_values)


def postcheck_numbers_v1(candidate: str, snapshot_values: object) -> NumberCheck:
    """The v1 token check, kept for comparison audits (ADR-008 Am1).

    Exact match after normalization; a token that is a standard display
    rounding (2-4 decimals) of a pool value also matches, tracked as
    `rounded` for audit. Integer-scale deviations still fail (BD-012).
    Month-years and framed bare years the evidence calendar supports
    are verified at their written precision first, tracked as
    `calendar` (TP-020).

    Implements: REQ-SI-INV-001 (ADR-006, BD-012 amendment; ADR-006 Am9)
    """
    pool = _values_pool(snapshot_values)
    floats = _pool_floats(snapshot_values)
    structural = _structural_tokens(snapshot_values)
    typed = _typed_ohlcv_pool(snapshot_values)
    matched: list[str] = []
    failed: list[str] = []
    rounded: list[str] = []
    structural_hits: list[str] = []
    mismatches: list[str] = []
    stripped = _normalize_dates(_strip_enumeration(candidate))
    checked, calendar = _strip_verified_calendar(stripped, _evidence_calendar(snapshot_values))
    for token in extract_numbers(checked):
        canon = _canon_token(token)
        if canon in structural:
            structural_hits.append(token)
            continue
        if canon in pool:
            stored_fields = typed.get(canon)
            if stored_fields and _field_mismatch(checked, token, stored_fields):
                # M2 phase 1: numerically present, semantically wrong
                # (open quoted as close) - quarantined like any fabrication.
                mismatches.append(token)
                continue
            matched.append(token)
            continue
        if any(_display_rounds_to(value, token) for value in floats):
            rounded.append(token)
            continue
        if any(
            _display_percent_of(value, token, candidate) for value in floats
        ):
            rounded.append(token)  # percent-display conversion (BD-015)
            continue
        failed.append(token)
    failed_all = failed + mismatches
    return NumberCheck(
        passed=not failed_all,
        matched=matched,
        failed=failed_all,
        rounded=rounded,
        structural=structural_hits,
        field_mismatch=mismatches,
        calendar=calendar,
        checked_text=checked,
    )


# ---- INV-001 v2: verify and flag (ADR-008) -------------------------------------

#: The marker appended to a word holding a number the post-check could not
#: verify (ADR-008). Plain ASCII, so both front-ends and the stored record
#: carry the same characters.
UNVERIFIED_MARKER = "[?]"

#: Shown while consecutive answers keep carrying unverified numbers; the
#: INV-001 abort it replaces is retired (ADR-008).
UNVERIFIED_STREAK_NOTICE = (
    "three answers in a row contained unverified numbers; check the data "
    "(/sync status) or start a new session"
)

#: Characters the marker goes in front of when they end the word: sentence
#: and clause punctuation, closing brackets and quotes, Markdown emphasis.
_MARK_BEFORE = frozenset(".,;:!?)]}\"'*_")


def _token_spans(text: str) -> list[tuple[str, int, int]]:
    """(token, start, end) exactly as the detector tokenizes, with positions kept.

    Identifier codes are blanked to the same length (not to one space as in
    extract_numbers), so every span indexes the original text.
    """
    blanked = _ID_CODE.sub(lambda match: " " * len(match.group()), text)
    return [(m.group().replace(",", ""), m.start(), m.end()) for m in _NUMBER_TOKEN.finditer(blanked)]


def unlocatable_unverified(candidate: str, check: NumberCheck) -> list[str]:
    """Unverified claims the marker cannot find in the candidate.

    Phase 2 (ADR-008 Am1): every claim carries its position in the text it
    was read from, so a claim whose position does not hold its text cannot
    be marked. Without claim positions (phase 1 verdicts), the detector read
    a transformed text (layout stripped, dates folded), and a failing token
    can exist there in a form the candidate never shows. Either way such a
    number cannot be marked, and the response must be withheld (fail-closed,
    ADR-008).

    Implements: REQ-SI-INV-001 (ADR-008)
    """
    if check.claims:
        return list(
            dict.fromkeys(
                claim.surface for claim in check.claims
                if not claim.verified and candidate[claim.start : claim.end] != claim.raw
            )
        )
    shown = Counter(token for token, _start, _end in _token_spans(candidate))
    checked = Counter(extract_numbers(check.checked_text))
    return [token for token in dict.fromkeys(check.failed) if shown[token] < checked[token]]


def _marker_position(text: str, end: int) -> int:
    """After the word that ends at or after `end`, in front of trailing punctuation."""
    stop = end
    while stop < len(text) and not text[stop].isspace() and text[stop] != "|":
        stop += 1
    while stop > end and text[stop - 1] in _MARK_BEFORE:
        stop -= 1
    return stop


def _insert_markers(text: str, positions: set[int]) -> str:
    marked = text
    for position in sorted(positions, reverse=True):
        marked = marked[:position] + UNVERIFIED_MARKER + marked[position:]
    return marked


def mark_claims(text: str, check: NumberCheck, offset: int = 0) -> str:
    """Mark exactly the unverified claims of `check` in `text` (ADR-008 Am1).

    `check` was computed on a text of which `text` is the part starting at
    `offset` (the answer without its pre-tool prelude). A verified number
    never carries the marker, even where the same digits are unverified
    elsewhere. Without claim positions, every occurrence of each unverified
    token is marked (the phase 1 rule).

    Implements: REQ-SI-INV-001 (ADR-008)
    """
    if not check.claims:
        return mark_unverified(text, list(dict.fromkeys(check.failed)))
    positions = {
        _marker_position(text, claim.end - offset)
        for claim in check.claims
        if not claim.verified and claim.start >= offset and claim.end - offset <= len(text)
    }
    return _insert_markers(text, positions)


def mark_unverified(text: str, tokens: Sequence[str]) -> str:
    """Append the unverified marker to every word holding one of the tokens.

    Every occurrence is marked (conservative). The marker goes in front of
    trailing punctuation and Markdown emphasis; a word gets one marker. A
    word ends at whitespace or a table cell bar. Removing the markers gives
    back the text unchanged. A surface that is not a single number (a date,
    a time, a number phrase; ADR-008 Am1) is marked wherever it occurs.

    Implements: REQ-SI-INV-001 (ADR-008)
    """
    wanted = set(tokens)
    if not wanted:
        return text
    positions: set[int] = set()
    for token, _start, end in _token_spans(text):
        if token in wanted:
            positions.add(_marker_position(text, end))
    for surface in wanted:
        if _NUMBER_TOKEN.fullmatch(surface):
            continue
        for match in re.finditer(rf"(?<![\w]){re.escape(surface)}(?!\d)", text):
            positions.add(_marker_position(text, match.end()))
    return _insert_markers(text, positions)


def unverified_detail(check: NumberCheck) -> list[dict[str, Any]]:
    """Per-claim record of the unverified numbers: class, subject, field, reason (ADR-008 Am1).

    Implements: REQ-SI-INV-001 (ADR-008)
    """
    from stockinsider.agent.guardrail_claims import FIELD_NAMES

    return [
        {
            "claim": claim.surface,
            "class": claim.cls,
            "subject": claim.subject,
            "field": FIELD_NAMES.get(claim.field or "", claim.field),
            "reason": claim.reason,
        }
        for claim in check.claims
        if not claim.verified
    ]


def unverified_notice(check: NumberCheck) -> str:
    """The notice naming the unverified numbers of an answer and why (ADR-008).

    Phase 2 (ADR-008 Am1): one group per distinct reason, in the order the
    claims appear; the phase 1 wording stays for numbers not found at all.

    Implements: REQ-SI-INV-001 (ADR-008)
    """
    if check.claims:
        groups: dict[str, list[str]] = {}
        for claim in check.claims:
            if not claim.verified:
                surfaces = groups.setdefault(claim.reason, [])
                if claim.surface not in surfaces:
                    surfaces.append(claim.surface)
        return "; ".join(
            f"unverified ({reason}; marked {UNVERIFIED_MARKER}): " + ", ".join(surfaces)
            for reason, surfaces in groups.items()
        )
    mismatched = list(dict.fromkeys(check.field_mismatch))
    missing = [token for token in dict.fromkeys(check.failed) if token not in set(mismatched)]
    parts = []
    if missing:
        parts.append(
            f"unverified (not found in this session's tool results; marked {UNVERIFIED_MARKER}): "
            + ", ".join(missing)
        )
    if mismatched:
        parts.append(
            f"unverified (quoted for a different field than the tool returned; marked {UNVERIFIED_MARKER}): "
            + ", ".join(mismatched)
        )
    return "; ".join(parts)


# ---- INV-002: epistemic filter -----------------------------------------------

#: TP-019 recall batch (ADR-006 Am8): unambiguous price-direction verbs
#: the fifth audit's held-out sentences used ("will double", "will
#: outperform") joined the base set; ambiguous verbs (gain, lose) stay
#: out to protect precision.
_VERBS = (
    "rise|fall|drop|climb|surge|plummet|rally|decline|increase|decrease|jump|slide|recover|collapse|"
    "double|triple|soar|tumble|crash|plunge|rebound|skyrocket|outperform|underperform"
)
_CAUSAL_VERBS = (
    "rises|falls|drops|climbs|surges|plummets|rallies|declines|increases|"
    "decreases|jumps|slides|recovers|collapses|rose|fell|dropped|jumped|"
    "rallied|surged|plummeted|declined|climbed|slid|recovered|collapsed|"
    "increased|decreased|doubled|tripled|soared|tumbled|crashed|plunged|"
    "rebounded|outperformed|underperformed|will"
)
EPISTEMIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "deterministic-prediction",
        re.compile(
            rf"\bwill\s+({_VERBS})\b"
            rf"|\b(guaranteed|certain|sure)\s+to\s+({_VERBS})\b"
            rf"|\bmust\s+(go\s+up|go\s+down|{_VERBS})\b"
            rf"|\bdefinitely\s+(will|{_VERBS})\b"
            rf"|\bprice\s+will\b",
            re.IGNORECASE,
        ),
    ),
    (
        "causal-claim",
        re.compile(
            rf"\b(because\s+of|due\s+to|caused)\b[^.!?]{{0,80}}?"
            rf"\b(price|stock|shares|valuation|index|market)\b[^.!?]{{0,60}}?"
            rf"\b({_CAUSAL_VERBS})\b",
            re.IGNORECASE,
        ),
    ),
    (
        # M3 (TP-017 PR-3b): four missing classes from the labeled
        # suite - going-to future, causal connectives, certainty
        # adverbs, and expectation imperatives - close the recall gap.
        "going-to-future",
        re.compile(
            rf"\bgoing\s+to\s+({_VERBS}|continue|reverse|hold)\b"
            rf"|\bwill\s+(continue|reverse|hold|repeat)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "causal-connective",
        re.compile(
            rf"\b(therefore|thus|hence|so\s+it|proves|proof\s+that)\b[^.!?]{{0,60}}?"
            rf"\b({_CAUSAL_VERBS}|fail(ed|ing)?|rall(y|ied)|jump(s|ed)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "certainty-adverb",
        re.compile(
            r"\b(without\s+doubt|undoubtedly|certainly|definitely)\b[^.!?]{0,60}?"
            r"\b(price|stock|shares|index|market|it)\b"
            r"|\b(jumped?|rallied?|surged?|fell|dropped?|climbed?)\b[^.!?]{0,40}?"
            r"\b(without\s+doubt|undoubtedly|certainly|definitely)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "expectation-imperative",
        re.compile(
            rf"\bexpect\b[^.!?]{{0,40}}?\bto\s+({_VERBS}|collapse|surge|plummet)\b",
            re.IGNORECASE,
        ),
    ),
    (
        # M3 recall batch (TP-018, ADR-006 Am6): modal-certainty framing
        # the audit's adversarial sentences used to slip through.
        "modal-certainty",
        re.compile(
            rf"\b(likely|set|on track|poised|slated|forecast|positioned|primed|"
            rf"expected|predicted|projected|anticipated)\b"
            rf"[^.!?]{0,30}?\bto\s+({_VERBS}|collapse|surge|plummet|continue|reverse|reach|exceed|double|triple)\b",
            re.IGNORECASE,
        ),
    ),
    # TP-019 recall batch (ADR-006 Am8): the fifth audit's held-out
    # classes - an adverb between "will" and the verb, effect-first
    # causal claims, driver verbs, and passive causation.
    (
        "adverbial-prediction",
        re.compile(rf"\bwill\s+[a-z]+ly\s+({_VERBS})\b", re.IGNORECASE),
    ),
    (
        "effect-first-causal",
        re.compile(
            rf"\b(price|prices|stock|shares|index|market)\b[^.!?]{{0,40}}?\b({_CAUSAL_VERBS})\b"
            rf"[^.!?]{{0,40}}?\b(because|due\s+to(?!\s+be\b)|as\s+a\s+result\s+of|"
            rf"on\s+the\s+back\s+of|driven\s+by)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "driver-verb",
        re.compile(
            r"\b(drive|drives|drove|send|sends|sent|push|pushes|pushed|lift|lifts|lifted|"
            r"drag|drags|dragged)\b[^.!?]{0,40}?\b(price|prices|stock|shares|index|market)\b"
            r"[^.!?]{0,20}?\b(higher|lower|up|down)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "passive-causation",
        re.compile(
            r"\b(sell-?off|rally|drop|decline|jump|surge|slump|rebound|move)\b[^.!?]{0,20}?"
            r"\b(was|were|is|are)\s+(caused|driven|triggered|sparked)\s+by\b",
            re.IGNORECASE,
        ),
    ),
    (
        # price targets and headed-for framing: a numeric level or a
        # direction asserted as the outcome ("should hit 700")
        "price-target",
        re.compile(
            r"\b(should|will|going\s+to)\s+(hit|reach|touch|test|top|breach)\s+(?:HK\$|US\$|\$)?\d"
            r"|\bheaded\s+(?:for|to|toward|towards)\s+(?:HK\$|US\$|\$)?\d"
            r"|\bheaded\s+(?:higher|lower|up|down)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "expectation-noun",
        re.compile(
            r"\bexpect\s+(?:a|an)\s+(?:\w+\s+)?(rebound|rally|drop|decline|recovery|correction|"
            r"breakout|sell-?off|bounce|pullback|crash)\b",
            re.IGNORECASE,
        ),
    ),
)

#: REPORTED speech is factual reporting, not the product's own
#: prediction (M3, TP-018). Fifth-audit narrowing (TP-019, ADR-006
#: Am8): TP-018b exempted a sentence carrying ANY reporting-or-
#: inference verb plus ANY source noun ANYWHERE, so "The chart
#: suggests the company will rise 20%" and "According to the report,
#: the stock will rise" laundered predictions. Attribution is now a
#: SPEECH ACT by an INSTITUTIONAL SOURCE, adjacent ("management
#: said", "the filing states"): inference verbs (suggests, indicates,
#: shows) and bare generic nouns (report, chart, analysis) never
#: attribute. The speech act must precede the claim inside the same
#: clause, or close the whole sentence as a tag (", the filing
#: states."). A fabricated attribution is out of a regex's reach and
#: is recorded as a known limit (ADR-006 Am8).
_SOURCE = (
    r"(?:management|the\s+company|the\s+issuer|the\s+board|"
    r"(?:the\s+|its\s+)?(?:ceo|cfo|chairman|chairwoman|chief\s+executive|chief\s+financial\s+officer)|"
    r"(?:a|the)\s+(?:company\s+)?spokes(?:person|man|woman)|"
    r"the\s+(?:company's\s+)?(?:filing|(?:earnings\s+|press\s+)?release|statement|announcement|prospectus)|"
    r"(?:(?:the\s+company's|management's|its)\s+)?guidance|the\s+regulator|the\s+exchange)"
)
_SPEECH_VERB = (
    r"(?:has\s+|have\s+|had\s+)?(?:said|says|announced|announces|stated|states|declared|declares|"
    r"reported|reports|guided|confirmed|confirms|disclosed|discloses)"
)
_SPEECH_ACT = re.compile(rf"\b{_SOURCE}\s+{_SPEECH_VERB}\b", re.IGNORECASE)
_SPEECH_TAG = re.compile(
    rf",\s*(?:as\s+)?{_SOURCE}\s+{_SPEECH_VERB}\s*[.!?\"')\]]*\s*$", re.IGNORECASE
)
_ACCORDING_TO_SOURCE = re.compile(
    r"\baccording\s+to\s+(?:the\s+|a\s+)?(?:company|management|issuer|filing|"
    r"(?:earnings\s+|press\s+)?release|statement|announcement|prospectus|regulator|"
    r"exchange|earnings\s+call)\b",
    re.IGNORECASE,
)

#: Hypothesis labels. An explicit label ("Hypothesis:", "(speculative)")
#: covers its whole sentence. A modal hedge covers only its own clause
#: (TP-019): "Revenue may dip, but the stock will double" used to pass
#: because "may" anywhere hedged everything. The modal "may" is matched
#: lower-case only - the month in "In May the stock will rise" is not a
#: hedge.
_EXPLICIT_LABEL = re.compile(r"hypothes[ie]s|speculat", re.IGNORECASE)
_MODAL_HEDGE = re.compile(
    r"\b(?:might|could|possibly|perhaps|conceivabl[ey])\b", re.IGNORECASE
)
_MODAL_MAY = re.compile(r"(?<![A-Za-z])may\b")
_CLAUSE_BREAK = re.compile(
    r";|\s+(?:but|whereas|yet)\s+|,\s*(?:and|so|while|although|though|however|"
    r"either\s+way|meanwhile|still|nonetheless)\b",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _clause_bounds(sentence: str, position: int) -> tuple[int, int]:
    """Start/end offsets of the clause that contains ``position``."""
    start, end = 0, len(sentence)
    for brk in _CLAUSE_BREAK.finditer(sentence):
        if brk.end() <= position:
            start = brk.end()
        elif brk.start() > position:
            end = brk.start()
            break
    return start, end


def _claim_is_excused(sentence: str, claim_start: int) -> bool:
    """True when a hedge or an adjacent institutional speech act covers the claim.

    Implements: REQ-SI-INV-002 (ADR-006 Am8; TP-019)
    """
    start, end = _clause_bounds(sentence, claim_start)
    clause = sentence[start:end]
    if _MODAL_HEDGE.search(clause) or _MODAL_MAY.search(clause):
        return True
    for attribution in (*_SPEECH_ACT.finditer(sentence), *_ACCORDING_TO_SOURCE.finditer(sentence)):
        if start <= attribution.start() and attribution.end() <= claim_start:
            return True
    return False


def _sentence_violates(sentence: str) -> bool:
    """True when some deterministic claim in the sentence is neither labeled nor attributed.

    Implements: REQ-SI-INV-002 (ADR-006 Am8; TP-019)
    """
    if _EXPLICIT_LABEL.search(sentence) or _SPEECH_TAG.search(sentence):
        return False
    for _name, pattern in EPISTEMIC_PATTERNS:
        for claim in pattern.finditer(sentence):
            if not _claim_is_excused(sentence, claim.start()):
                return True
    return False


@dataclass(frozen=True)
class EpistemicCheck:
    """INV-002 single-pass verdict: violations and the stripped text.

    Implements: REQ-SI-INV-002 (ADR-006)
    """

    passed: bool
    violations: list[str]
    clean_text: str


def epistemic_filter(candidate: str) -> EpistemicCheck:
    """Strip deterministic claims/predictions; labeled speculation passes.

    A sentence violating a pattern survives only when every matched
    claim carries a hypothesis label (sentence-wide explicit label, or
    a modal hedge in the claim's own clause) or is reported speech of
    an institutional source (TP-019, ADR-006 Am8).

    Implements: REQ-SI-INV-002 (ADR-006)
    """
    violations: list[str] = []
    kept: list[str] = []
    for sentence in _sentences(candidate):
        if _sentence_violates(sentence):
            violations.append(sentence.strip())
        else:
            kept.append(sentence)
    return EpistemicCheck(
        passed=not violations,
        violations=violations,
        clean_text=" ".join(kept).strip(),
    )


@dataclass(frozen=True)
class EpistemicOutcome:
    """INV-002 outcome after the one allowed regeneration attempt.

    Implements: REQ-SI-INV-002 (ADR-006)
    """

    displayed: str
    refused: bool
    violations_total: int


_REGENERATION_REMINDER = (
    "constraint reminder: no deterministic causal claims or price predictions; "
    "speculation must carry an explicit hypothesis label (INV-002)."
)

_REFUSAL = (
    "refused: the response could not be made epistemically safe (INV-002). "
    "hypothesis: the requested judgment is speculative; no deterministic "
    "causal claim or price prediction is stated here."
)


def run_with_regeneration(
    candidate: str,
    regenerator: Callable[[str], str],
) -> EpistemicOutcome:
    """Strip violations, regenerate once, then refuse with a safe summary.

    Implements: REQ-SI-INV-002 (ADR-006)
    """
    first = epistemic_filter(candidate)
    if first.passed:
        return EpistemicOutcome(displayed=candidate, refused=False, violations_total=0)
    regenerated = regenerator(f"{_REGENERATION_REMINDER}\n{first.clean_text}")
    second = epistemic_filter(regenerated)
    if second.passed:
        return EpistemicOutcome(displayed=regenerated, refused=False, violations_total=len(first.violations))
    return EpistemicOutcome(
        displayed=_REFUSAL,
        refused=True,
        violations_total=len(first.violations) + len(second.violations),
    )


# ---- combined verdict and session counters -----------------------------------


@dataclass(frozen=True)
class GuardrailVerdict:
    """Authoritative post-check verdict for one candidate response.

    Implements: REQ-SI-INV-001, REQ-SI-INV-002 (ADR-006)
    """

    display_text: str
    #: withheld: the response is not displayed (language policy, or an
    #: unverified number that cannot be marked - ADR-008)
    quarantined: bool
    degraded: str | None
    number_check: NumberCheck
    epistemic: EpistemicCheck
    language_ok: bool
    violations: list[str]
    #: numbers the post-check could not verify (ADR-008)
    unverified: list[str] = field(default_factory=list)
    #: displayed with every unverified number marked (ADR-008)
    flagged: bool = False


def run_postcheck(candidate: str, snapshot_values: object) -> GuardrailVerdict:
    """Run INV-001 + INV-002 + language in one authoritative verdict.

    Unverified numbers flag the response: the display text carries the
    unverified marker on each of them (ADR-008). The response is withheld
    only for a language violation, or when an unverified number cannot be
    located for marking (fail-closed: the old degraded line). Epistemic
    violations strip for display; the loop composes regeneration on top.

    Implements: REQ-SI-INV-001, REQ-SI-INV-002, REQ-SI-INV-003 (ADR-006, ADR-008)
    """
    language_ok = is_english_only(candidate)
    numbers = postcheck_numbers(candidate, snapshot_values)
    epi = epistemic_filter(candidate)
    unverified = list(dict.fromkeys(numbers.failed))
    unmarkable = unlocatable_unverified(candidate, numbers) if unverified else []
    quarantined = bool(unmarkable) or not language_ok
    flagged = bool(unverified) and not quarantined
    degraded = None
    if unmarkable:
        parts = ["data unavailable for: " + ", ".join(numbers.failed)]
        if numbers.field_mismatch:
            parts.append(
                "field mismatch (numeric present, wrong field quoted): "
                + ", ".join(numbers.field_mismatch)
            )
        degraded = "; ".join(parts)
    if quarantined:
        display = degraded if degraded else "response withheld: language policy violation (GOV-001)"
    elif epi.violations:
        display = mark_unverified(epi.clean_text, unverified) if flagged else epi.clean_text
    else:
        display = mark_claims(candidate, numbers) if flagged else candidate
    violations = list(epi.violations)
    if not language_ok:
        violations.append("language policy (GOV-001)")
    return GuardrailVerdict(
        display_text=display,
        quarantined=quarantined,
        degraded=degraded,
        number_check=numbers,
        epistemic=epi,
        language_ok=language_ok,
        violations=violations,
        unverified=unverified,
        flagged=flagged,
    )


class PostCheckCounter:
    """Session counters: INV-001 unverified streak and INV-002 violation budget.

    ADR-008 retired the INV-001 abort: the streak of consecutive answers
    with unverified numbers now only makes a notice due. The INV-002
    budget still aborts.

    Implements: REQ-SI-INV-001, REQ-SI-INV-002 (ADR-006, ADR-008)
    """

    def __init__(self, *, number_limit: int = 3, epistemic_limit: int = 2) -> None:
        """Set the notice streak (3) and the INV-002 abort budget (>2)."""
        self._number_limit = number_limit
        self._epistemic_limit = epistemic_limit
        self._number_streak = 0
        self._epistemic_total = 0

    def record(self, verdict: GuardrailVerdict) -> str | None:
        """Record one verdict; return the abort reason when the INV-002 budget trips.

        Implements: REQ-SI-INV-001, REQ-SI-INV-002 (ADR-006, ADR-008)
        """
        if verdict.number_check.passed:
            self._number_streak = 0
        else:
            self._number_streak += 1
        self._epistemic_total += len(verdict.epistemic.violations)
        if self._epistemic_total > self._epistemic_limit:
            return "abort:epistemic"
        return None

    @property
    def number_notice_due(self) -> bool:
        """True while the streak of answers with unverified numbers is at the limit or beyond.

        Implements: REQ-SI-INV-001 (ADR-008)
        """
        return self._number_streak >= self._number_limit
