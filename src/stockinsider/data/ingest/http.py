"""HTTP transport seam for ingestion adapters (stdlib, egress-gated).

Responses are classified once, here: success carries the body; every
failure becomes an explicit TransportError with a kind — the sync
service never inspects raw sockets (INV-003). The EODHD 402 signal
(plan exhausted) is classified as rate-limited and reported with the
ADR-002 policy wording; no retry is ever attempted by this layer.

The page seam (TP-035) serves feed and article fetches: it returns
raw bytes (feeds declare their own encoding), identifies itself with
a fixed User-Agent, caps the body size, and re-validates every
redirect hop against the egress whitelist, so a redirect can never
lead off the whitelist (SEC-003).

Implements: REQ-SI-INV-003, REQ-SI-SEC-003 (ADR-002)
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

from stockinsider.shared.egress import validate_egress_url

#: Transport contract: (url, params) -> FetchResult (or raises TransportError).
Transport = Callable[[str, dict[str, str]], "FetchResult"]

TIMEOUT_SECONDS = 15

#: Fixed, honest identification for feed and page fetches (TP-035).
USER_AGENT = "StockInsider/0.1 (personal research tool; local storage, no redistribution)"

#: Feed and article bodies larger than this are refused, not truncated.
MAX_PAGE_BYTES = 5_000_000

CAPACITY_MESSAGE = (
    "EODHD daily call limit reached (HTTP 402): capacity is bought, "
    "never worked around with retries (ADR-002); remaining items are "
    "reported as deferred"
)


class TransportError(RuntimeError):
    """Classified transport failure (explicit, fail-closed).

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind  # "rate-limited" | "http-error" | "network" | "too-large"
        self.status = status  # the HTTP status for "http-error", else None


@dataclass(frozen=True)
class FetchResult:
    """One successful response: status code and body text.

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    status: int
    body: str


def stdlib_fetch(url: str, params: dict[str, str]) -> FetchResult:
    """Live transport over stdlib urllib; egress-gated, one shot, no retry.

    Implements: REQ-SI-SEC-003 (ADR-002)
    """
    full = f"{url}?{urlencode(params)}"
    validate_egress_url(full)
    try:
        with urllib.request.urlopen(full, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 — whitelist-checked
            return FetchResult(resp.status, resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 402:
            raise TransportError("rate-limited", CAPACITY_MESSAGE) from exc
        raise TransportError("http-error", f"HTTP {exc.code} from {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TransportError("network", f"network failure reaching {url}: {exc}") from exc


@dataclass(frozen=True)
class PageResult:
    """One fetched page or feed: status, raw bytes, content type, final URL.

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    status: int
    body: bytes
    content_type: str
    final_url: str


#: Page transport contract: url -> PageResult (or raises TransportError).
PageTransport = Callable[[str], PageResult]


class _EgressCheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Every redirect target passes the egress whitelist before it is followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        """Validate the redirect target before urllib follows it.

        Implements: REQ-SI-SEC-003 (ADR-002)
        """
        validate_egress_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def stdlib_fetch_page(url: str) -> PageResult:
    """Fetch one feed or article page; egress-gated per hop, one shot, no retry.

    An HTTP error carries its status (callers separate article-level
    4xx from infrastructure 5xx); an egress violation, on the first
    URL or on a redirect, propagates as EgressViolationError.

    Implements: REQ-SI-SEC-003, REQ-SI-INV-003 (ADR-002)
    """
    validate_egress_url(url)
    opener = urllib.request.build_opener(_EgressCheckedRedirects)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.9",
        },
    )
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 — whitelist-checked per hop
            body = resp.read(MAX_PAGE_BYTES + 1)
            if len(body) > MAX_PAGE_BYTES:
                raise TransportError("too-large", f"body over {MAX_PAGE_BYTES} bytes from {url}")
            return PageResult(resp.status, body, resp.headers.get("Content-Type", ""), resp.geturl())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise TransportError("rate-limited", f"HTTP 429 from {url}", status=429) from exc
        raise TransportError("http-error", f"HTTP {exc.code} from {url}", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TransportError("network", f"network failure reaching {url}: {exc}") from exc
