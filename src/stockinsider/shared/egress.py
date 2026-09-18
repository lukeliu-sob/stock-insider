"""Egress whitelist and outbound-URL validation (SEC-003, fail-closed).

The static whitelist holds the data-vendor domains; dynamically
resolved endpoints (provider base URLs from the layered configuration)
are passed per-call via extra_allowed. Non-whitelisted hosts and
non-HTTPS schemes are rejected explicitly — never silently allowed.

Implements: REQ-SI-SEC-003 (ADR-004)
"""

from __future__ import annotations

from urllib.parse import urlparse

#: Static data-vendor domains (ADR-002); the HTTP choke point adopts
#: this when the data side lands (S2 evidence: egress denials).
#: BD-010: the EODHD API host is the apex domain (eodhd.com/api/...);
#: the decision-era "api." subdomain does not resolve (verified live
#: 2026-09-18: eodhd.com 403-serves, api.eodhd.com dead).
EGRESS_WHITELIST: frozenset[str] = frozenset(
    {
        "eodhd.com",
        "api.gdeltproject.org",
    }
)


class EgressViolationError(RuntimeError):
    """Explicit outbound-URL rejection (SEC-003).

    Implements: REQ-SI-SEC-003 (ADR-004)
    """


def _domain_allowed(host: str, allowed: frozenset[str]) -> bool:
    lowered = host.lower().rstrip(".")
    return any(lowered == domain or lowered.endswith("." + domain) for domain in allowed)


def validate_egress_url(url: str, *, extra_allowed: tuple[str, ...] = ()) -> None:
    """Validate an outbound URL: HTTPS required, host must be whitelisted.

    extra_allowed: dynamically resolved endpoints (e.g., provider base
    URLs); their subdomains are allowed too. Everything else fails
    closed with an explicit error.

    Implements: REQ-SI-SEC-003 (ADR-004)
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise EgressViolationError(f"egress refused: non-HTTPS scheme {parsed.scheme!r} in {url!r} (SEC-003)")
    host = parsed.hostname or ""
    allowed = EGRESS_WHITELIST | frozenset(name.lower() for name in extra_allowed)
    if not _domain_allowed(host, allowed):
        raise EgressViolationError(
            f"egress refused: host {host!r} not in whitelist (SEC-003); allowed: {sorted(allowed)}"
        )
