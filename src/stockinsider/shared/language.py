"""Runtime English-only policy helpers (FR-014 / GOV-001).

The CI language gate governs repository artifacts; these helpers
govern runtime output at render paths. Complementary, not redundant.
The only product-level exception (Chinese company aliases in the
symbol map) is enforced at the symbol layer, not here.

Implements: REQ-SI-FR-014, REQ-SI-GOV-001 (ADR-004)
"""

from __future__ import annotations

import re

#: CJK ideographs, CJK symbols/punctuation, and fullwidth forms.
CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


class LanguagePolicyError(RuntimeError):
    """Explicit runtime language-policy violation (GOV-001).

    Implements: REQ-SI-GOV-001 (ADR-004)
    """


def is_english_only(text: str) -> bool:
    """True when text carries no CJK ideographs, punctuation, or fullwidth forms.

    Implements: REQ-SI-FR-014 (ADR-004)
    """
    return not CJK_PATTERN.search(text)


def assert_english(text: str, *, context: str = "") -> None:
    """Raise LanguagePolicyError on any CJK content; context names the source.

    Implements: REQ-SI-GOV-001 (ADR-004)
    """
    match = CJK_PATTERN.search(text)
    if match:
        where = f" ({context})" if context else ""
        raise LanguagePolicyError(
            f"non-English output detected{where}: character {match.group(0)!r} "
            "(GOV-001: English only; the permitted exception is Chinese company "
            "aliases in the symbol map)"
        )
