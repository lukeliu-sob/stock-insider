"""Runtime English-only policy helpers (FR-014 / GOV-001).

The CI language gate governs repository artifacts; these helpers
govern runtime output at render paths. Complementary, not redundant.
The only product-level exception (Chinese company aliases in the
symbol map) is enforced at the symbol layer, not here.

M4 (TP-018) + fourth-audit widening (TP-018b): "English only" is a
positive allowlist, not a CJK blocklist - the old CJK-only check
passed Cyrillic, Greek, Hangul and every other non-Latin script as
"English".

Fifth-audit redesign (TP-019, ADR-004 Am4): the policy governs
LANGUAGE, and language lives in letters and digits. The closed
character list of TP-018b kept withholding whole correct answers for
a checkmark, a triangle, a thin space or a chart emoji. Now:

- letters must be Latin script (any Latin block), plus a closed set
  of Greek letters used as math/finance symbols (alpha, beta, gamma,
  delta, sigma, mu, pi); any other letter fails closed;
- digits must be ASCII (Arabic-Indic, Devanagari and other script
  digits fail closed);
- CJK ideographs, CJK punctuation and fullwidth forms fail closed;
- control and invisible format characters fail closed (bidi
  overrides could disguise text), except the emoji joiners;
- everything else - punctuation, symbols, arrows, math signs,
  currency, emoji, spaces - is not language and passes.

Implements: REQ-SI-FR-014, REQ-SI-GOV-001 (ADR-004; TP-018, TP-019)
"""

from __future__ import annotations

import re
import unicodedata

#: The allowlist, as one character class:
#:  - printable ASCII (letters, digits, punctuation, space)
#:  - Latin-1 supplement + Latin Extended-A (accented letters)
#:  - typographic set: dashes, quotes, ellipsis, hyphens, spaces
#:  - arrows and comparison/math signs used in market prose
#:  - currency symbols, (c)(r)(tm), closed report-emoji set
_LATIN_ALLOW = (
    "\t\n\r"
    "\u0020-\u007e"  # printable ASCII
    "\u00a0-\u00ff"  # Latin-1 supplement
    "\u0100-\u017f"  # Latin Extended-A
    "\u2013\u2014\u2018\u2019\u201c\u201d\u2026\u00b7"  # typographic
    "\u2010\u2011\u202f"  # hyphens + narrow no-break space
    "\u2190\u2191\u2192\u2193\u2194\u21d2"  # arrows
    "\u2022\u25aa\u25cf"  # bullets
    "\u2264\u2265\u2248\u2260\u00b1\u00d7\u00f7\u2212"  # comparison/math
    "\u20ac\u00a3\u00a5"  # currency
    "\u00a9\u00ae\u2122"  # (c) (r) (tm)
    "\u2705\u274c\u26a0\U0001f4c8\U0001f4c9\U0001f4ca"  # report emoji (closed set)
    "\ufe0f"  # emoji variation selector
)

ENGLISH_ONLY = re.compile("[" + _LATIN_ALLOW + "]*")

#: Kept for existing references: the CJK ranges the original check
#: covered (a strict subset of what ENGLISH_ONLY now rejects).
CJK_PATTERN = re.compile("[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


class LanguagePolicyError(RuntimeError):
    """Explicit runtime language-policy violation (GOV-001).

    Implements: REQ-SI-GOV-001 (ADR-004)
    """


#: Greek letters that finance/math prose uses as symbols (TP-019).
_MATH_GREEK = frozenset("αβγδΔσΣμπ")

#: Invisible format characters that may appear in well-formed emoji
#: sequences (zero-width joiner/non-joiner). Every other format
#: character - bidi overrides, isolates, marks - fails closed.
_ALLOWED_FORMAT = frozenset("‌‍")


def _char_allowed(char: str) -> bool:
    """One character against the script-based policy (TP-019).

    Implements: REQ-SI-GOV-001 (ADR-004 Am4; TP-019)
    """
    if ENGLISH_ONLY.fullmatch(char):
        return True  # the TP-018b allowlist stays a fast path
    if CJK_PATTERN.match(char):
        return False
    category = unicodedata.category(char)
    if category.startswith("L"):
        return unicodedata.name(char, "").startswith("LATIN ") or char in _MATH_GREEK
    if category == "Nd":
        return False  # non-ASCII digits: ASCII ones took the fast path
    if category == "Cf":
        return char in _ALLOWED_FORMAT
    if category in ("Cc", "Cs", "Co", "Cn"):
        return False
    return True  # punctuation, symbols, marks, separators, other numbers


def _first_disallowed(text: str) -> "str | None":
    for char in text:
        if not _char_allowed(char):
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

