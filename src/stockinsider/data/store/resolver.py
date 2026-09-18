"""Symbol resolution: the verified path into the symbol map (INV-004).

Nothing enters the watchlist without a resolution record produced here
and an explicit user confirmation. Resolution has two sources: the
seeded built-in benchmark indices, and the EODHD search API behind an
injectable transport (offline tests inject fakes; the live transport
uses stdlib urllib and the shared egress whitelist).

Implements: REQ-SI-FR-004, REQ-SI-INV-004 (ADR-002)
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from stockinsider.shared.egress import validate_egress_url

#: Transport contract: (url, params) -> response body text.
Transport = Callable[[str, dict[str, str]], str]

EODHD_SEARCH_URL = "https://eodhd.com/api/search/{query}"
EODHD_KEY_ENV = "EODHD_API_KEY"

#: Built-in benchmark indices (FR-001): always tracked, never watchlist-managed.
BENCHMARK_INDICES: tuple[dict[str, Any], ...] = (
    {
        "canonical_symbol": "HSI.IND",
        "exchange": "IND",
        "official_name": "Hang Seng Index",
        "asset_type": "index",
        "aliases": ["Hang Seng", "HSI"],
    },
    {
        "canonical_symbol": "HSTECH.IND",
        "exchange": "IND",
        "official_name": "Hang Seng TECH Index",
        "asset_type": "index",
        "aliases": ["HSTECH", "Hang Seng Tech"],
    },
    {
        "canonical_symbol": "GSPC.IND",
        "exchange": "IND",
        "official_name": "S&P 500 Index",
        "asset_type": "index",
        "aliases": ["S&P 500", "GSPC"],
    },
    {
        "canonical_symbol": "NDX.IND",
        "exchange": "IND",
        "official_name": "Nasdaq-100 Index",
        "asset_type": "index",
        "aliases": ["Nasdaq 100", "NDX"],
    },
)


class ResolverUnavailable(RuntimeError):
    """No live search path is configured (explicit, never silent-empty).

    Implements: REQ-SI-INV-003 (ADR-002)
    """


@dataclass(frozen=True)
class Resolution:
    """One verified candidate from a symbol search.

    Implements: REQ-SI-FR-004 (ADR-002)
    """

    canonical_symbol: str
    exchange: str
    official_name: str
    asset_type: str = "stock"
    aliases: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Render for tool/CLI surfaces (aliases as a list).

        Implements: REQ-SI-FR-004 (ADR-002)
        """
        return {
            "canonical_symbol": self.canonical_symbol,
            "exchange": self.exchange,
            "official_name": self.official_name,
            "asset_type": self.asset_type,
            "aliases": list(self.aliases),
        }


class SymbolResolver:
    """Resolve user mentions to verified symbol candidates.

    Order: seeded benchmark match (verified immediately), then the
    live search transport when configured. Unresolvable queries return
    an empty list (searched and not found — distinct from an
    unconfigured resolver, which raises ResolverUnavailable).

    Implements: REQ-SI-FR-004, REQ-SI-INV-004 (ADR-002)
    """

    def __init__(self, transport: Transport | None = None, api_key: str | None = None) -> None:
        self._transport = transport
        self._api_key = api_key if api_key is not None else os.environ.get(EODHD_KEY_ENV)

    def search(self, query: str) -> list[Resolution]:
        """Return candidates for a mention; deterministic seed match first.

        Implements: REQ-SI-FR-004 (ADR-002)
        """
        q = query.strip()
        if not q:
            return []
        seeds = [
            Resolution(
                canonical_symbol=entry["canonical_symbol"],
                exchange=entry["exchange"],
                official_name=entry["official_name"],
                asset_type=entry["asset_type"],
                aliases=tuple(entry["aliases"]),
            )
            for entry in BENCHMARK_INDICES
            if self._seed_matches(entry, q)
        ]
        if seeds:
            return seeds
        if self._transport is None or self._api_key is None:
            raise ResolverUnavailable(
                "symbol search is not configured: set EODHD_API_KEY (free tier) to enable live resolution (INV-003)"
            )
        body = self._transport(EODHD_SEARCH_URL.format(query=quote(q)), {"api_token": self._api_key})
        return parse_search_response(body)

    @staticmethod
    def _seed_matches(entry: dict[str, Any], q: str) -> bool:
        lowered = q.lower()
        names = [entry["official_name"], *entry["aliases"], entry["canonical_symbol"]]
        return any(lowered == name.lower() or lowered == name.lower().replace(" ", "") for name in names)


def parse_search_response(body: str) -> list[Resolution]:
    """Parse an EODHD search response body into resolutions (pure).

    Implements: REQ-SI-INV-003 (ADR-002)
    """
    try:
        rows = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ResolverUnavailable(f"EODHD search returned malformed JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise ResolverUnavailable("EODHD search returned a non-list payload")
    out: list[Resolution] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = row.get("Code")
        exchange = row.get("Exchange")
        name = row.get("Name")
        if not (isinstance(code, str) and isinstance(exchange, str) and isinstance(name, str)):
            continue  # malformed row: skipped, never repaired (INV-003)
        asset_type = "index" if "index" in str(row.get("Type", "")).lower() else "stock"
        out.append(
            Resolution(
                canonical_symbol=f"{code}.{exchange}",
                exchange=exchange,
                official_name=name,
                asset_type=asset_type,
            )
        )
    return out


def stdlib_transport(url: str, params: dict[str, str]) -> str:
    """Live HTTP transport over stdlib urllib, egress-gated (SEC-003).

    Implements: REQ-SI-SEC-003 (ADR-002)
    """
    full = f"{url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    validate_egress_url(full)
    with urllib.request.urlopen(full, timeout=10) as resp:  # noqa: S310 — whitelist-checked
        return resp.read().decode("utf-8")


def record_resolution(conn: Any, resolution: Resolution) -> None:
    """Persist a verified resolution into the symbol map.

    Implements: REQ-SI-FR-004, REQ-SI-INV-004 (ADR-002)
    """
    resolved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        conn.execute(
            """
            INSERT INTO symbols (canonical_symbol, exchange, official_name,
                                 asset_type, aliases, verified, source, resolved_at)
            VALUES (?, ?, ?, ?, ?, 1, 'eodhd-search', ?)
            ON CONFLICT(canonical_symbol) DO UPDATE SET
                official_name = excluded.official_name,
                aliases = excluded.aliases,
                verified = 1,
                resolved_at = excluded.resolved_at
            """,
            (
                resolution.canonical_symbol,
                resolution.exchange,
                resolution.official_name,
                resolution.asset_type,
                json.dumps(list(resolution.aliases)),
                resolved_at,
            ),
        )


def seed_benchmarks(conn: Any) -> None:
    """Seed the built-in benchmark indices into the symbol map.

    Implements: REQ-SI-FR-001 (ADR-002)
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        for entry in BENCHMARK_INDICES:
            conn.execute(
                """
                INSERT OR IGNORE INTO symbols (canonical_symbol, exchange, official_name,
                                               asset_type, aliases, verified, source, resolved_at)
                VALUES (?, ?, ?, ?, ?, 1, 'seed', ?)
                """,
                (
                    entry["canonical_symbol"],
                    entry["exchange"],
                    entry["official_name"],
                    entry["asset_type"],
                    json.dumps(entry["aliases"]),
                    now,
                ),
            )


def backfill_window(days: int = 5 * 365) -> tuple[str, str]:
    """The default 5-year backfill window ending today (FR-004).

    Implements: REQ-SI-FR-004 (ADR-002)
    """
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days)
    return start.isoformat(), today.isoformat()
