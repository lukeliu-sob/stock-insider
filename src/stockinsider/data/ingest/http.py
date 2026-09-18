"""HTTP transport seam for ingestion adapters (stdlib, egress-gated).

Responses are classified once, here: success carries the body; every
failure becomes an explicit TransportError with a kind — the sync
service never inspects raw sockets (INV-003). The EODHD 402 signal
(plan exhausted) is classified as rate-limited and reported with the
ADR-002 policy wording; no retry is ever attempted by this layer.

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

CAPACITY_MESSAGE = (
    "EODHD daily call limit reached (HTTP 402): capacity is bought, "
    "never worked around with retries (ADR-002); remaining items are "
    "reported as deferred"
)


class TransportError(RuntimeError):
    """Classified transport failure (explicit, fail-closed).

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # "rate-limited" | "http-error" | "network"


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
