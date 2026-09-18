"""Data side: ingestion adapters, storage, deterministic computation.

Consumed only through this facade package (blueprint §5 dependency
rules); the LLM runtime reaches it only via agent/registry tools.

Implements: REQ-SI-FR-001, REQ-SI-FR-004 (ADR-002, ADR-003)
"""

from __future__ import annotations

from stockinsider.data.store import (
    ACTIVE_CAP,
    DataStore,
    ResolverUnavailable,
    SchemaVersionError,
    SymbolResolver,
    WatchlistError,
    WatchlistService,
    open_data_store,
)

__all__ = [
    "ACTIVE_CAP",
    "DataStore",
    "ResolverUnavailable",
    "SchemaVersionError",
    "SymbolResolver",
    "WatchlistError",
    "WatchlistService",
    "open_data_store",
]
