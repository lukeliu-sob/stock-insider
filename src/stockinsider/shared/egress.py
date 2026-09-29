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
        # Model-runtime hosts (M9, TP-017 PR-3b): the provider layer now
        # validates through this same whitelist; the chat/embedding
        # endpoints must be first-class citizens.
        "api.deepseek.com",
        "api.openai.com",
    }
)


class EgressViolationError(RuntimeError):
    """Explicit outbound-URL rejection (SEC-003).

    Implements: REQ-SI-SEC-003 (ADR-004)
    """


def extra_hosts_from_env(environ: "dict[str, str] | None" = None) -> tuple[str, ...]:
    """Owner-declared extension hosts (ADR-004 Am2, TP-018).

    The ``EGRESS_EXTRA_HOSTS`` entry (comma-separated domain names) in
    the local environment extends the allowed set for provider
    endpoints at resolution time. This is an explicit, auditable owner
    decision for OpenRouter-class or local model endpoints - never a
    silent default (INV-003). Malformed entries (empty tokens, URLs
    with schemes, whitespace-only) are skipped, not guessed.

    Implements: REQ-SI-SEC-003 (ADR-004 Am2)
    """
    import os

    if environ is not None:
        raw = environ.get("EGRESS_EXTRA_HOSTS", "")
    else:
        raw = os.getenv("EGRESS_EXTRA_HOSTS", "")
    hosts: list[str] = []
    for token in raw.split(","):
        name = token.strip().lower().rstrip(".")
        if name and "/" not in name and ":" not in name:
            hosts.append(name)
    return tuple(hosts)


def provider_egress_allowed() -> tuple[str, ...]:
    """The full allowed-host tuple for provider endpoint validation.

    Implements: REQ-SI-SEC-003 (ADR-004 Am2)
    """
    return extra_hosts_from_env()


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
    host = (parsed.hostname or "").lower().rstrip(".")
    loopback = host in ("localhost", "::1") or host.startswith("127.")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        # Fourth-audit fix (TP-018b, ADR-004 Am2): plain HTTP remains
        # refused for everything that can leave the machine - except an
        # explicit loopback endpoint (local model runtimes). Loopback
        # traffic does not egress; refusing it made the documented local
        # endpoint path unusable.
        raise EgressViolationError(f"egress refused: non-HTTPS scheme {parsed.scheme!r} in {url!r} (SEC-003)")
    allowed = EGRESS_WHITELIST | frozenset(name.lower() for name in extra_allowed)
    if not loopback and not _domain_allowed(host, allowed):
        raise EgressViolationError(
            f"egress refused: host {host!r} not in whitelist (SEC-003); allowed: {sorted(allowed)}"
        )
