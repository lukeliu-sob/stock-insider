"""Runtime guardrail: INV-001 numeric post-check and INV-002 epistemic filter.

Semantics follow docs/architecture/invariants.md exactly: numeric
mismatches quarantine the response and degrade it to an explicit
data-unavailable statement; epistemic violations strip and regenerate
once, then refuse with a hypothesis-labeled summary. Wiring into the
response pipeline (quarantine event storage, degradation display,
session abort) lands with the agent loop (TP-007); this module is the
authoritative, fully testable verdict library.

Number matching is exact-after-normalization (no tolerance: a ±1
mismatch fails), and derived numbers are NOT accepted unless a compute
tool registered them in the snapshot — precision over convenience
(ADR-006).

Implements: REQ-SI-INV-001, REQ-SI-INV-002, REQ-SI-INV-003 (ADR-006)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from stockinsider.shared.language import is_english_only

# ---- INV-001: numeric provenance post-check ---------------------------------

_NUMBER_TOKEN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


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

    Implements: REQ-SI-INV-001 (ADR-006)
    """
    return [token.replace(",", "") for token in _NUMBER_TOKEN.findall(text)]


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
            for token in extract_numbers(value):
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
            for token in extract_numbers(value):
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


def postcheck_numbers(candidate: str, snapshot_values: object) -> NumberCheck:
    """Verify every numeric token against the snapshot pool.

    Exact match after normalization; a token that is a standard display
    rounding (2-4 decimals) of a pool value also matches, tracked as
    `rounded` for audit. Integer-scale deviations still fail (BD-012).

    Implements: REQ-SI-INV-001 (ADR-006, BD-012 amendment)
    """
    pool = _values_pool(snapshot_values)
    floats = _pool_floats(snapshot_values)
    matched: list[str] = []
    failed: list[str] = []
    rounded: list[str] = []
    for token in extract_numbers(candidate):
        canon = _canon_token(token)
        if canon in pool:
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
    return NumberCheck(passed=not failed, matched=matched, failed=failed, rounded=rounded)


# ---- INV-002: epistemic filter -----------------------------------------------

_VERBS = "rise|fall|drop|climb|surge|plummet|rally|decline|increase|decrease|jump|slide|recover|collapse"
_CAUSAL_VERBS = (
    "rises|falls|drops|climbs|surges|plummets|rallies|declines|increases|"
    "decreases|jumps|slides|recovers|collapses|rose|fell|dropped|jumped|"
    "rallied|surged|plummeted|declined|climbed|slid|recovered|collapsed|"
    "increased|decreased|will"
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
)

_HYPOTHESIS = re.compile(
    r"hypothesis|speculat|\bmight\b|\bcould\b|\bmay\b|possibly|conceivab",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


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

    A sentence violating a pattern survives only when it carries an
    explicit hypothesis marker (INV-002's labeling requirement).

    Implements: REQ-SI-INV-002 (ADR-006)
    """
    violations: list[str] = []
    kept: list[str] = []
    for sentence in _sentences(candidate):
        has_pattern = any(pattern.search(sentence) for _name, pattern in EPISTEMIC_PATTERNS)
        labeled = _HYPOTHESIS.search(sentence) is not None
        if has_pattern and not labeled:
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
    quarantined: bool
    degraded: str | None
    number_check: NumberCheck
    epistemic: EpistemicCheck
    language_ok: bool
    violations: list[str]


def run_postcheck(candidate: str, snapshot_values: object) -> GuardrailVerdict:
    """Run INV-001 + INV-002 + language in one authoritative verdict.

    Quarantine (never display the original): numeric mismatch or
    language violation. Epistemic violations strip for display; the
    loop (TP-007) composes regeneration on top of this verdict.

    Implements: REQ-SI-INV-001, REQ-SI-INV-002, REQ-SI-INV-003 (ADR-006)
    """
    language_ok = is_english_only(candidate)
    numbers = postcheck_numbers(candidate, snapshot_values)
    epi = epistemic_filter(candidate)
    quarantined = (not numbers.passed) or not language_ok
    degraded = None
    if not numbers.passed:
        degraded = "data unavailable for: " + ", ".join(numbers.failed)
    if quarantined:
        display = degraded if degraded else "response withheld: language policy violation (GOV-001)"
    elif epi.violations:
        display = epi.clean_text
    else:
        display = candidate
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
    )


class PostCheckCounter:
    """Session counters: INV-001 three-strike and INV-002 violation budget.

    Implements: REQ-SI-INV-001, REQ-SI-INV-002 (ADR-006)
    """

    def __init__(self, *, number_limit: int = 3, epistemic_limit: int = 2) -> None:
        """Set the abort thresholds (invariant-doc defaults: 3 and >2)."""
        self._number_limit = number_limit
        self._epistemic_limit = epistemic_limit
        self._number_streak = 0
        self._epistemic_total = 0

    def record(self, verdict: GuardrailVerdict) -> str | None:
        """Record one verdict; return the abort reason when thresholds trip.

        Implements: REQ-SI-INV-001, REQ-SI-INV-002 (ADR-006)
        """
        if verdict.number_check.passed:
            self._number_streak = 0
        else:
            self._number_streak += 1
        self._epistemic_total += len(verdict.epistemic.violations)
        if self._number_streak >= self._number_limit:
            return "abort:number"
        if self._epistemic_total > self._epistemic_limit:
            return "abort:epistemic"
        return None
