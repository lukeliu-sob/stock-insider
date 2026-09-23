"""Schema migrations for the authoritative SQLite store.

One migration per schema version; migrations are append-only, run in
transactions, and the code refuses to open a database whose schema
version is newer than the code knows (memory-design §4 — explicit
version error, never a silent misread).

Implements: REQ-SI-FR-003, REQ-SI-FR-004 (ADR-003)
"""

from __future__ import annotations

MIGRATION_V1 = """
CREATE TABLE symbols (
    canonical_symbol TEXT PRIMARY KEY,
    exchange TEXT NOT NULL,
    official_name TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'index')),
    aliases TEXT NOT NULL DEFAULT '[]',
    verified INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);

CREATE TABLE watchlist (
    canonical_symbol TEXT PRIMARY KEY REFERENCES symbols(canonical_symbol),
    added_at TEXT NOT NULL,
    added_via TEXT NOT NULL CHECK (added_via IN ('cli', 'agent-tool')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed'))
);

CREATE TABLE market_bars (
    canonical_symbol TEXT NOT NULL REFERENCES symbols(canonical_symbol),
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL NOT NULL,
    volume INTEGER,
    currency TEXT NOT NULL,
    adjusted INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (canonical_symbol, date)
);

CREATE TABLE fundamentals (
    canonical_symbol TEXT NOT NULL REFERENCES symbols(canonical_symbol),
    period_end TEXT NOT NULL,
    statement_type TEXT NOT NULL CHECK (statement_type IN ('income', 'balance', 'cashflow')),
    data TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (canonical_symbol, period_end, statement_type)
);

CREATE TABLE news (
    news_id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_norm TEXT NOT NULL,
    title TEXT NOT NULL,
    domain TEXT NOT NULL,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source_query TEXT NOT NULL,
    symbol TEXT,
    relevance_score REAL NOT NULL,
    kept INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX idx_news_url ON news(url_norm);

CREATE TABLE news_quarantine (
    news_id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_norm TEXT NOT NULL,
    title TEXT NOT NULL,
    domain TEXT NOT NULL,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source_query TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE event_scores (
    news_id INTEGER NOT NULL REFERENCES news(news_id),
    direction TEXT NOT NULL CHECK (direction IN ('positive', 'neutral', 'negative')),
    strength INTEGER NOT NULL CHECK (strength BETWEEN 1 AND 5),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    rationale TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    PRIMARY KEY (news_id)
);

CREATE TABLE fx_rates (
    pair TEXT NOT NULL,
    date TEXT NOT NULL,
    rate REAL NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (pair, date)
);

CREATE TABLE sync_state (
    track TEXT PRIMARY KEY,
    cursor TEXT,
    last_run_at TEXT,
    last_status TEXT,
    calls_today INTEGER NOT NULL DEFAULT 0,
    calls_date TEXT
);

CREATE TABLE sync_gaps (
    canonical_symbol TEXT NOT NULL,
    from_date TEXT NOT NULL,
    to_date TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    PRIMARY KEY (canonical_symbol, from_date, to_date)
);
"""

#: Migration v2 (TP-009): EODHD rows carry raw OHLC plus a separate
#: adjusted_close; storing both preserves fidelity for the compute layer.
MIGRATION_V2 = "ALTER TABLE market_bars ADD COLUMN adjusted_close REAL;"

#: Migration v3 (TP-010): company profile rows sourced from the
#: fundamentals feed's General section.
MIGRATION_V3 = """
CREATE TABLE symbol_profiles (
    canonical_symbol TEXT PRIMARY KEY REFERENCES symbols(canonical_symbol),
    name TEXT,
    exchange TEXT,
    sector TEXT,
    industry TEXT,
    country TEXT,
    updated_at TEXT NOT NULL
);
"""

#: Migration v4 (TP-011b): extend the v1 news tables to the TP-011
#: corpus shape (append-only ALTERs). The v1 global url_norm unique
#: index is replaced by a per-bucket one: the same article may
#: legitimately land in two buckets via two queries (design S3 Key A
#: is bucket-scoped). failing_gate/detail supersede v1's free-text
#: reason for quarantine visibility (INV-003).
MIGRATION_V4 = """
ALTER TABLE news ADD COLUMN url_raw TEXT;
ALTER TABLE news ADD COLUMN language TEXT NOT NULL DEFAULT '';
ALTER TABLE news ADD COLUMN sourcecountry TEXT;
ALTER TABLE news ADD COLUMN score_breakdown TEXT NOT NULL DEFAULT '{}';
ALTER TABLE news ADD COLUMN token_sources TEXT NOT NULL DEFAULT '[]';
ALTER TABLE news ADD COLUMN source_tier REAL NOT NULL DEFAULT 0.0;
DROP INDEX idx_news_url;
CREATE UNIQUE INDEX idx_news_bucket_url ON news(symbol, url_norm);
CREATE INDEX idx_news_bucket_seen ON news(symbol, published_at);
ALTER TABLE news_quarantine ADD COLUMN bucket TEXT NOT NULL DEFAULT '';
ALTER TABLE news_quarantine ADD COLUMN failing_gate TEXT NOT NULL DEFAULT '';
ALTER TABLE news_quarantine ADD COLUMN detail TEXT NOT NULL DEFAULT '';
"""

#: Append-only migration list: index i holds migration to version i+1.
MIGRATIONS: tuple[str, ...] = (MIGRATION_V1, MIGRATION_V2, MIGRATION_V3, MIGRATION_V4)

#: Latest schema version this code understands.
SCHEMA_VERSION = len(MIGRATIONS)
