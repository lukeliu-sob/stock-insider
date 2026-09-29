"""Runtime English-only policy helpers (FR-014 / GOV-001).

The CI language gate governs repository artifacts; these helpers
govern runtime output at render paths. Complementary, not redundant.
The only product-level exception (Chinese company aliases in the
symbol map) is enforced at the symbol layer, not here.

M4 (TP-018): "English only" is a positive allowlist, not a CJK
blocklist - the old CJK-only check passed Cyrillic, Greek, Hangul
and every other non-Latin script as "English". A response is
English-only when every character is ASCII, Latin-1 supplement
letters/punctuation, or a member of a small closed set of
typographic marks common in financial prose. Fail closed on
anything else.

Implements: REQ-SI-FR-014, REQ-SI-GOV-001 (ADR-004; TP-018)
"""

from __future__ import annotations

import re

#: The allowlist, as one character class:
#:  - printable ASCII (letters, digits, punctuation, space)
#:  - Latin-1 supplement letters and punctuation (accented letters)
#:  - closed typographic set: dashes, curly quotes, ellipsis, middot,
#:    math/currency signs that appear in market prose
_LATIN_ALLOW = (
    "\t\n\r"
    "\u0020-\u007e"  # printable ASCII
    "\u00a0-\u00ff"  # Latin-1 supplement (letters + punctuation)
    "\u2013\u2014\u2018\u2019\u201c\u201d\u2026\u00b7"  # typographic
    "\u00b1\u00d7\u00f7\u2212\u2248"  # math signs in prose
    "\u20ac\u00a3\u00a5"  # EUR/GBP/JPY currency symbols
    "\u00a9\u00ae\u2122"  # (c) (r) (tm)
)

ENGLISH_ONLY = re.compile("[" + _LATIN_ALLOW + "]*")

#: Kept for existing references: the CJK ranges the original check
#: covered (a strict subset of what ENGLISH_ONLY now rejects).
CJK_PATTERN = re.compile("[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


class LanguagePolicyError(RuntimeError):
    """Explicit runtime language-policy violation (GOV-001).

    Implements: REQ-SI-GOV-001 (ADR-004)
    """


def _first_disallowed(text: str) -> "str | None":
    for char in text:
        if not ENGLISH_ONLY.fullmatch(char):
            return char
    return None


def is_english_only(text: str) -> bool:
    """True when every character is in the Latin/ASCII allowlist (M4).

    Implements: REQ-SI-FR-014 (ADR-004; TP-018)
    """
    return _first_disallowed(text) is None


def first_violation(text: str) -> "str | None":
    """Return the first disallowed character (None when compliant).

    Implements: REQ-SI-GOV-001 (ADR-004; TP-018)
    """
    return _first_disallowed(text)


def assert_english(text: str, *, context: str = "") -> None:
    """Raise LanguagePolicyError on any non-allowlist content.

    Implements: REQ-SI-GOV-001 (ADR-004)
    """
    bad = _first_disallowed(text)
    if bad is not None:
        point = " in " + context if context else ""
        raise LanguagePolicyError(
            "language policy violation" + point + ": non-Latin character "
            + repr(bad) + " (U+" + format(ord(bad), "04X")
            + "); output must be English-only (GOV-001)"
        )
