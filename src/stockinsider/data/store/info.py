"""Deterministic info snapshot: render the FR-005 display from the DB only.

Every numeric line carries its data date; missing sections render
explicit unavailable lines; no provider call ever happens here
(FR-005: exit-0 with providers unreachable).

Implements: REQ-SI-FR-005, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from stockinsider.data.compute import format_compact, max_abs_daily_move, move_vs

MOVES_WINDOW = 21  # ~one trading month of sessions


class SymbolUnknown(RuntimeError):
    """The symbol has no stored data (explicit, never a fabricated snapshot).

    Implements: REQ-SI-INV-003 (ADR-002)
    """


def _latest_bars(conn: sqlite3.Connection, symbol: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT date, close, adjusted_close, volume FROM market_bars "
        "WHERE canonical_symbol = ? ORDER BY date DESC LIMIT ?",
        (symbol, limit),
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


def render_info(conn: sqlite3.Connection, symbol: str) -> list[str]:
    """Render the deterministic snapshot lines for a symbol.

    Implements: REQ-SI-FR-005 (ADR-002)
    """
    bars = _latest_bars(conn, symbol, MOVES_WINDOW + 5)
    if not bars:
        raise SymbolUnknown(
            f"{symbol}: no stored market data; run `stockinsider watch add {symbol}` "
            "and `stockinsider sync` first (INV-003)"
        )
    profile = conn.execute(
        "SELECT name, exchange, sector, industry FROM symbol_profiles WHERE canonical_symbol = ?",
        (symbol,),
    ).fetchone()
    lines: list[str] = []
    if profile is not None:
        bits = [symbol, str(profile["name"] or ""), f"({profile['exchange'] or '?'})"]
        if profile["sector"]:
            bits.append(str(profile["sector"]))
        lines.append(" — ".join([b for b in bits if b]))
    else:
        lines.append(f"{symbol} — profile unavailable (fundamentals feed not ingested)")
    last = bars[-1]
    prev = bars[-2] if len(bars) >= 2 else None
    close_line = (
        f"quote ({last['date']}, native currency): close {last['close']:g} | adjusted {last['adjusted_close']:g}"
        if last["adjusted_close"] is not None
        else f"quote ({last['date']}, native currency): close {last['close']:g}"
    )
    if last["volume"] is not None:
        close_line += f" | volume {format_compact(float(last['volume']))}"
    lines.append(close_line)
    if prev is not None:
        from stockinsider.data.compute import pct_change

        try:
            lines.append(
                f"day change ({last['date']} vs {prev['date']}): {pct_change(prev['close'], last['close']):+.2f}%"
            )
        except Exception:  # noqa: BLE001 — zero base: explicit, never fabricated
            lines.append(f"day change ({last['date']}): unavailable (zero base)")
    big = max_abs_daily_move(bars)
    if big is not None:
        lines.append(f"largest daily move (last {len(bars)} sessions): {big['abs_pct']:.2f}% abs on {big['date']}")
    versus = move_vs(bars, 20)
    if versus is not None:
        lines.append(f"vs 20 sessions ago ({versus['from_date']} -> {versus['date']}): {versus['pct']:+.2f}%")
    from stockinsider.data.ingest.fundamentals import ALL_REQUIRED_FIELDS, STATEMENTS

    latest = conn.execute(
        "SELECT period_end, statement_type, data FROM fundamentals WHERE canonical_symbol = ? "
        "ORDER BY period_end DESC LIMIT 3",
        (symbol,),
    ).fetchall()
    if not latest:
        lines.append(
            "fundamentals: unavailable (Fundamentals Data Feed not in the current plan; explicit, not omitted)"
        )
        return lines
    by_type = {row["statement_type"]: row for row in latest}
    period = max(row["period_end"] for row in latest)
    values: dict[str, float] = {}
    for row in latest:
        values.update({k: v for k, v in json.loads(row["data"]).items() if isinstance(v, (int, float))})
    parts = []
    label = {
        "totalRevenue": "revenue",
        "netIncome": "net income",
        "totalAssets": "assets",
        "totalStockholdersEquity": "equity",
        "totalCashFromOperatingActivities": "OCF",
    }
    for field in ALL_REQUIRED_FIELDS:
        if values.get(field) is not None:
            parts.append(f"{label.get(field, field)} {format_compact(float(values[field]))}")
    lines.append(
        f"fundamentals (quarter ending {period}): " + " | ".join(parts)
        if parts
        else f"fundamentals (quarter ending {period}): no required fields present"
    )
    _ = by_type, STATEMENTS
    return lines
