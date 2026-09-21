"""Fundamentals adapter: quarterly statements, validation, coverage (FR-002).

One request per symbol against /api/fundamentals/{symbol} — the
vendor charges 10 call units per request, and the endpoint 403s on
plans without the Fundamentals Data Feed. Both facts shape this
module: the budget spend is 10 units, and a 403 raises
FundamentalsNotInPlan (sync records it once per run and skips the
track until re-probed — never a silent empty corpus).

Storage: full statement JSON per (symbol, period, statement_type) in
the fundamentals table; the profile (General section) lands in
symbol_profiles (migration v3). Coverage is COMPUTED, never assumed:
the 8-quarter x required-field grid with explicit gap records.

Implements: REQ-SI-FR-002, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from stockinsider.data.ingest.http import Transport, TransportError, stdlib_fetch
from stockinsider.shared.envfile import env_value

FUNDAMENTALS_URL = "https://eodhd.com/api/fundamentals/{symbol}"
EODHD_KEY_ENV = "EODHD_API_KEY"
#: The vendor's per-request call price (api-limits page).
CALL_COST = 10

#: statement_type -> (vendor section, required fields for FR-002 coverage)
STATEMENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "income": ("Income_Statement", ("totalRevenue", "netIncome")),
    "balance": ("Balance_Sheet", ("totalAssets", "totalStockholdersEquity")),
    "cashflow": ("Cash_Flow_", ("totalCashFromOperatingActivities",)),
}
ALL_REQUIRED_FIELDS: tuple[str, ...] = tuple(field for _, fields in STATEMENTS.values() for field in fields)
COVERAGE_QUARTERS = 8

PROFILE_FIELDS = ("Name", "Exchange", "Sector", "Industry", "CountryName")


class FundamentalsNotInPlan(RuntimeError):
    """HTTP 403: the current EODHD plan lacks the fundamentals feed.

    Implements: REQ-SI-INV-003 (ADR-002)
    """


class MarketKeyMissing(RuntimeError):
    """No EODHD key configured (explicit; never a fake empty corpus).

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    # Reused name for parity with the market adapter's messaging.


class InvalidFundamentals(RuntimeError):
    """Payload failed structural validation; nothing stored.

    Implements: REQ-SI-INV-003 (ADR-002)
    """


def parse_fundamentals(body: str, symbol: str) -> dict[str, Any]:
    """Parse and structurally validate a fundamentals payload (pure).

    Implements: REQ-SI-INV-003 (ADR-002)
    """
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise InvalidFundamentals(f"{symbol}: malformed JSON from fundamentals: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidFundamentals(f"{symbol}: fundamentals payload is not an object")
    return data


def extract_statements(data: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    """Flatten vendor sections into statement rows (period-validated).

    Implements: REQ-SI-FR-002 (ADR-002)
    """
    rows: list[dict[str, Any]] = []
    for statement_type, (section, _fields) in STATEMENTS.items():
        quarterly = (data.get(section) or {}).get("quarterly")
        if not isinstance(quarterly, dict):
            continue  # section absent: coverage will record the gap explicitly
        for period_end, values in quarterly.items():
            if not isinstance(period_end, str) or len(period_end) != 10 or not isinstance(values, dict):
                raise InvalidFundamentals(
                    f"{symbol}: malformed {statement_type} entry for {period_end!r}; batch refused"
                )
            rows.append(
                {
                    "canonical_symbol": symbol,
                    "period_end": period_end,
                    "statement_type": statement_type,
                    "data": json.dumps(values, sort_keys=True),
                }
            )
    return rows


def store_statements(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    """Upsert statement rows transactionally; returns stored count.

    Implements: REQ-SI-FR-002 (ADR-002)
    """
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO fundamentals (canonical_symbol, period_end, statement_type,
                                          data, source, fetched_at)
                VALUES (?, ?, ?, ?, 'eodhd-fundamentals', ?)
                ON CONFLICT(canonical_symbol, period_end, statement_type) DO UPDATE SET
                    data = excluded.data, fetched_at = excluded.fetched_at
                """,
                (row["canonical_symbol"], row["period_end"], row["statement_type"], row["data"], fetched_at),
            )
    return len(rows)


def store_profile(conn: sqlite3.Connection, data: dict[str, Any], symbol: str) -> bool:
    """Persist the General section as the symbol profile (migration v3 table).

    Implements: REQ-SI-FR-005 (ADR-002)
    """
    general = data.get("General")
    if not isinstance(general, dict):
        return False
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        conn.execute(
            """
            INSERT INTO symbol_profiles (canonical_symbol, name, exchange, sector,
                                         industry, country, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_symbol) DO UPDATE SET
                name = excluded.name, exchange = excluded.exchange, sector = excluded.sector,
                industry = excluded.industry, country = excluded.country,
                updated_at = excluded.updated_at
            """,
            (
                symbol,
                general.get("Name"),
                general.get("Exchange"),
                general.get("Sector"),
                general.get("Industry"),
                general.get("CountryName"),
                updated_at,
            ),
        )
    return True


class EodhdFundamentalsAdapter:
    """Fetch + parse + store one symbol's fundamentals (10 budget units).

    Implements: REQ-SI-FR-002, REQ-SI-INV-003 (ADR-002)
    """

    def __init__(self, transport: Transport | None = None, api_key: str | None = None) -> None:
        self._injected = transport is not None
        self._api_key: str | None = api_key if api_key is not None else (env_value(EODHD_KEY_ENV) or None)
        self._transport: Transport | None = transport if transport is not None else stdlib_fetch

    def is_live(self) -> bool:
        """True when fetching is possible (key for the default path; any injection).

        Implements: REQ-SI-INV-003 (ADR-002)
        """
        return self._transport is not None and (self._api_key is not None or self._injected)

    def fetch_and_store(self, conn: sqlite3.Connection, symbol: str) -> dict[str, Any]:
        """One request: parse, store statements + profile, report counts.

        Implements: REQ-SI-FR-002 (ADR-002)
        """
        if not self.is_live():
            raise MarketKeyMissing(
                "fundamentals ingestion is not configured: set EODHD_API_KEY "
                "(real environment variable or the local env file) (INV-003)"
            )
        assert self._transport is not None
        token = self._api_key or ""
        try:
            result = self._transport(FUNDAMENTALS_URL.format(symbol=symbol), {"api_token": token, "fmt": "json"})
        except TransportError as exc:
            if exc.kind == "http-error" and "403" in str(exc):
                raise FundamentalsNotInPlan(
                    f"{symbol}: HTTP 403 — the current EODHD plan does not include "
                    "the Fundamentals Data Feed; add the package to enable it (INV-003)"
                ) from exc
            raise
        data = parse_fundamentals(result.body, symbol)
        rows = extract_statements(data, symbol)
        stored = store_statements(conn, rows)
        profile = store_profile(conn, data, symbol)
        return {"statements": stored, "profile": profile}


def coverage(conn: sqlite3.Connection, symbol: str) -> dict[str, Any]:
    """Compute the FR-002 coverage grid: 8 quarters x required fields.

    Implements: REQ-SI-FR-002 (ADR-002)
    """
    periods = [
        row["period_end"]
        for row in conn.execute(
            "SELECT DISTINCT period_end FROM fundamentals WHERE canonical_symbol = ? ORDER BY period_end DESC LIMIT ?",
            (symbol, COVERAGE_QUARTERS),
        ).fetchall()
    ]
    latest_n = sorted(periods, reverse=True)
    present: set[tuple[str, str]] = set()
    for row in conn.execute(
        "SELECT period_end, statement_type, data FROM fundamentals WHERE canonical_symbol = ?",
        (symbol,),
    ).fetchall():
        values = json.loads(row["data"])
        for statement_type, (_section, fields) in STATEMENTS.items():
            if row["statement_type"] != statement_type:
                continue
            for field in fields:
                if values.get(field) is not None:
                    present.add((row["period_end"], field))
    grid: list[dict[str, Any]] = []
    filled = 0
    cells = 0
    for period in latest_n:
        for field in ALL_REQUIRED_FIELDS:
            has = (period, field) in present
            filled += int(has)
            cells += 1
            if not has:
                grid.append({"period_end": period, "field": field})
    ratio = (filled / cells) if cells else 0.0
    return {
        "symbol": symbol,
        "quarters": len(latest_n),
        "quarters_expected": COVERAGE_QUARTERS,
        "cells": cells,
        "cells_filled": filled,
        "ratio": round(ratio, 4),
        "meets_threshold": ratio >= 0.99 and len(latest_n) >= COVERAGE_QUARTERS,
        "gaps": grid,
    }
