"""Layer-one sanitization of untrusted news content (SEC-002).

Total, deterministic transformation: same input, same output, no
configuration, no exceptions raised — the sanitizer always yields
displayable text. Storage keeps raw text (evidence, quarantine
included); only the egress path into model context sanitizes
(news-filtering-design §6). This module is the one legal shared
dependency of both ``agent/context`` and ``data/ingest``.

Neutralization strategy: unicode is NFKC-normalized first (collapsing
fullwidth and compatibility forms used to obfuscate directives),
control/zero-width/bidi characters are stripped, then a closed set of
instruction-like patterns is replaced with an inert marker. The
marker is visible and auditable — sanitization never silently
rephrases content.

Implements: REQ-SI-SEC-002 (ADR-004, TP-012 amendment)
"""

from __future__ import annotations

import re
from unicodedata import normalize as _unicode_normalize

#: Inert replacement for neutralized directive text.
NEUTRALIZED_MARKER = "[neutralized]"

#: Control characters, zero-width and bidi marks (post-NFKC strip).
_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2060\u2066-\u2069\ufeff]"
)

#: Role-spoofing markers at line starts or after whitespace.
_ROLE_MARKER_RE = re.compile(r"(?i)(?<![a-z0-9])(?:system|assistant|user|developer|tool)\s*:\s*")

#: Instruction-override directives (closed set; case-insensitive).
_DIRECTIVE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\b"),
    re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\b"),
    re.compile(r"(?i)\bforget\s+(?:all\s+)?(?:previous|prior|above|earlier)\b"),
    re.compile(r"(?i)\bnew\s+instructions?\b"),
    re.compile(r"(?i)\byour\s+(?:new\s+)?instructions?\s+are\s+now\b"),
    re.compile(r"(?i)\byou\s+are\s+now\b"),
    re.compile(r"(?i)\b(?:act|pretend)\s+as\s+(?:if\s+you\s+are\s+)?(?:a|an|the)\b"),
    re.compile(r"(?i)\bpretend\s+(?:that\s+)?you\s+(?:are|were)\b"),
    re.compile(r"(?i)\bact\s+like\s+(?:you\s+are\s+)?(?:a|an|the)\b"),
    re.compile(r"(?i)\bjailbreak\b"),
    re.compile(r"(?i)\bdeveloper\s+mode\b"),
    re.compile(r"(?i)\bdo\s+anything\s+now\b"),
    re.compile(
        r"(?i)\bai\s*:\s*",
    ),
    re.compile(r"(?i)\[?(?:tool\s+(?:result|output|call))\]?"),
)

_NEUTRALIZE_RE = re.compile(
    "|".join(pattern.pattern.replace("(?i)", "", 1) for pattern in _DIRECTIVE_RES),
    re.IGNORECASE,
)


def sanitize_text(text: str) -> str:
    """Return the sanitized form of one untrusted text.

    Implements: REQ-SI-SEC-002 (ADR-004, TP-012 amendment)
    """
    normalized = _unicode_normalize("NFKC", text)
    stripped = _CONTROL_RE.sub("", normalized)
    stripped = _ROLE_MARKER_RE.sub(NEUTRALIZED_MARKER + " ", stripped)
    return _NEUTRALIZE_RE.sub(NEUTRALIZED_MARKER, stripped)


def sanitize_batch(texts: list[str]) -> list[str]:
    """Sanitize a batch (order-preserving).

    Implements: REQ-SI-SEC-002 (ADR-004, TP-012 amendment)
    """
    return [sanitize_text(text) for text in texts]


def has_active_directives(text: str) -> bool:
    """True when any directive pattern is still active in ``text``.

    Post-check helper: run on sanitizer output; a True result means
    the sanitizer failed (adversarial detection, not a filter).

    Implements: REQ-SI-SEC-002 (ADR-004, TP-012 amendment)
    """
    probe = _CONTROL_RE.sub("", _unicode_normalize("NFKC", text))
    if _ROLE_MARKER_RE.search(probe):
        return True
    return _NEUTRALIZE_RE.search(probe) is not None
