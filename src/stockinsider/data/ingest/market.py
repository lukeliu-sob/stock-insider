"""EODHD end-of-day market adapter: fetch, validate, store (fail-closed).

One request covers a whole date range (call cost is per request, not
per bar — the free-tier budget's best friend). Rows are strictly
validated before storage; **any invalid row fails the entire symbol
batch** with nothing stored (transactional, INV-003 — no partial
writes, no silent row skips).

Storage semantics (schema v2): raw OHLC in open/high/low/close with
``adjusted = 0``; the vendor's ``adjusted_close`` lands in its own
column; the computation layer (TP-013) picks the series per indicator.

Implements: REQ-SI-FR-001, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from stockinsider.data.ingest.http import FetchResult, Transport, TransportError, stdlib_fetch
from stockinsider.shared.envfile import env_value

EOD_URL = "https://eodhd.com/api/eod/{symbol}"
EODHD_KEY_ENV = "EODHD_API_KEY"

#: Native currency per exchange suffix (FR-001); indices are dimensionless.
CURRENCY_BY_EXCHANGE: dict[str, str] = {"HK": "HKD", "US": "USD", "IND": "POINTS"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REQUIRED_FLOATS = ("open", "high", "low", "close")


class MarketKeyMissing(RuntimeError):
    """No EODHD key configured (explicit; never a fake empty result).

    Implements: REQ-SI-INV-003 (ADR-002)
    """


class InvalidMarketData(RuntimeError):
    """A batch failed schema validation; nothing was stored.

    Implements: REQ-SI-INV-003 (ADR-002)
    """


def _row_is_valid(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    date = row.get("date")
    if not isinstance(date, str) or not _DATE_RE.match(date):
        return False
    for field in _REQUIRED_FLOATS:
        value = row.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            return False
    volume = row.get("volume")
    if volume is not None and not (isinstance(volume, int) and not isinstance(volume, bool)):
        return False
    adjusted = row.get("adjusted_close")
    if adjusted is not None and not isinstance(adjusted, (int, float)):
        return False
    return True


def parse_eod_rows(body: str, symbol: str) -> list[dict[str, Any]]:
    """Parse and strictly validate an EOD payload (pure; ascending by date).

    Implements: REQ-SI-INV-003 (ADR-002)
    """
    try:
        rows = json.loads(body)
    except json.JSONDecodeError as exc:
        raise TransportError("network", f"malformed JSON from EOD for {symbol}: {exc}") from exc
    if not isinstance(rows, list):
        raise InvalidMarketData(f"{symbol}: EOD payload is not a list")
    cleaned: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not _row_is_valid(row):
            raise InvalidMarketData(
                f"{symbol}: row {index} failed schema validation "
                f"(date/OHLC/volume shape); batch refused, nothing stored"
            )
        cleaned.append(
            {
                "date": row["date"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "adjusted_close": float(row["adjusted_close"]) if row.get("adjusted_close") is not None else None,
                "volume": int(row["volume"]) if row.get("volume") is not None else None,
            }
        )
    cleaned.sort(key=lambda r: r["date"])
    return cleaned


class EodhdMarketAdapter:
    """Fetch EOD bars for one symbol over a date range (one request).

    Implements: REQ-SI-FR-001 (ADR-002)
    """

    def __init__(self, transport: Transport | None = None, api_key: str | None = None) -> None:
        """Wire like the resolver: explicit injection wins; else env-or-file key.

        An explicitly injected transport counts as configured (tests and
        alternate wirings); the key requirement guards only the default
        stdlib live path.
        """
        self._injected = transport is not None
        if api_key is not None:
            self._api_key: str | None = api_key
        else:
            self._api_key = env_value(EODHD_KEY_ENV) or None
        self._transport: Transport | None = transport if transport is not None else stdlib_fetch

    def is_live(self) -> bool:
        """True when fetching is possible (key for the default path; any injection).

        Implements: REQ-SI-INV-003 (ADR-002)
        """
        return self._transport is not None and (self._api_key is not None or self._injected)

    def fetch_eod(self, symbol: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
        """Return validated bars for [from_date, to_date] (ascending).

        Implements: REQ-SI-FR-001, REQ-SI-INV-003 (ADR-002)
        """
        if not self.is_live():
            raise MarketKeyMissing(
                "market ingestion is not configured: set EODHD_API_KEY "
                "(real environment variable or the local env file) (INV-003)"
            )
        assert self._transport is not None
        token = self._api_key or ""
        params = {
            "api_token": token,
            "from": from_date,
            "to": to_date,
            "fmt": "json",
            "order": "a",
        }
        result: FetchResult = self._transport(EOD_URL.format(symbol=symbol), params)
        return parse_eod_rows(result.body, symbol)


def store_bars(conn: sqlite3.Connection, symbol: str, rows: list[dict[str, Any]]) -> int:
    """Upsert one symbol's batch transactionally; returns stored count.

    Implements: REQ-SI-FR-001 (ADR-002)
    """
    exchange = symbol.rsplit(".", 1)[-1]
    currency = CURRENCY_BY_EXCHANGE.get(exchange, "UNKNOWN")
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO market_bars (canonical_symbol, date, open, high, low, close,
                                         volume, currency, adjusted, adjusted_close,
                                         source, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'eodhd-eod', ?)
                ON CONFLICT(canonical_symbol, date) DO UPDATE SET
                    open = excluded.open, high = excluded.high, low = excluded.low,
                    close = excluded.close, volume = excluded.volume,
                    adjusted_close = excluded.adjusted_close,
                    fetched_at = excluded.fetched_at
                """,
                (
                    symbol,
                    row["date"],
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                    currency,
                    row["adjusted_close"],
                    fetched_at,
                ),
            )
    return len(rows)
