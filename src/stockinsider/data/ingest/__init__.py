"""Ingestion adapters: market, fundamentals, news, FX.

Adapters are vendor-seamed (ADR-002), fail-closed (INV-003), and the
only writers of domain tables (memory-design §1). The market path is
live since TP-009: EODHD EOD adapter, free-tier call budget, index-
derived calendars, gap detection and backfill. Fundamentals (TP-010)
and news (TP-011) follow the same shape: transport seam in, validated
rows out, transactional storage.

Implements: REQ-SI-FR-001, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

from stockinsider.data.ingest.budget import CallBudget, daily_cap
from stockinsider.data.ingest.calendar import CalendarUnavailable, missing_ranges, trading_dates
from stockinsider.data.ingest.http import FetchResult, TransportError, stdlib_fetch
from stockinsider.data.ingest.market import (
    EodhdMarketAdapter,
    InvalidMarketData,
    MarketKeyMissing,
    store_bars,
)
from stockinsider.data.ingest.sync import SyncService, sync_status

__all__ = [
    "CalendarUnavailable",
    "CallBudget",
    "EodhdMarketAdapter",
    "FetchResult",
    "InvalidMarketData",
    "MarketKeyMissing",
    "SyncService",
    "TransportError",
    "daily_cap",
    "missing_ranges",
    "store_bars",
    "stdlib_fetch",
    "sync_status",
    "trading_dates",
]
