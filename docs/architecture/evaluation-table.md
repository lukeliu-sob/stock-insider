# Candidate Evaluation Table — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/architecture/evaluation-table.md` (course deliverable D2.8) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Related | ADR-001 (runtime, topology), ADR-002 (data vendor, news), ADR-003 (storage, vector) |

The comparison that justifies the chosen architecture. Scores are qualitative judgments from the owner-supervised discussion rounds (R1–R8), recorded here for audit; quantitative evidence will accumulate in the evaluation logbook as the evaluation set runs. Scale: 1 (poor) – 5 (excellent). **Bold** = chosen.

## 1. Agent runtime (ADR-001)

| Criterion (weight) | **Self-built loop** | LangGraph | pydantic-ai | smolagents |
|---|---|---|---|---|
| Context-pipeline control / course governance (×3) | **5** | 2 | 3 | 2 |
| Guardrail hook fit (×3) | **5** | 3 | 3 | 2 |
| Dependency weight (×2) | **5** | 2 | 3 | 3 |
| Offline testability (×2) | **5** | 3 | 3 | 3 |
| Community maintenance (×1) | 2 | 5 | 4 | 4 |
| **Weighted total (max 55)** | **50** | 30 | 33 | 30 |

## 2. Deployment topology (ADR-001)

| Criterion | **In-process package** | Local service/daemon |
|---|---|---|
| Deployment simplicity | **5** | 2 |
| Failure modes | **5** | 2 |
| CI testability | **5** | 3 |
| Future extraction path | 4 (facade seam) | 5 |
| **Total** | **19** | 12 |

## 3. Commercial data source (ADR-002)

| Criterion (weight) | **EODHD** | Futu/Tiger OpenAPI | IBKR | Tushare Pro | Polygon/FMP |
|---|---|---|---|---|---|
| HK fundamentals completeness (×3) | **4** | 5 | 5 | 2 | 1 |
| Statelessness / REST (×2) | **5** | 1 (gateway) | 1 (gateway) | 5 | 5 |
| Offline mockability (×2) | **5** | 4 | 3 | 4 | 5 |
| Cost (×1) | 3 | 5 (free w/ account) | 4 | 4 | 3 |
| Backfill throughput / rate limits (×1) | 4 | 3 (quotas) | 3 | 3 | 4 |
| **Weighted total (max 45)** | **38** | 32 | 31 | 24 | 20 |

## 4. Vector store (ADR-003)

| Criterion (weight) | **sqlite-vec** | chromadb | faiss | pgvector |
|---|---|---|---|---|
| Dependency weight (×3) | **5** | 2 | 4 | 1 (needs server) |
| Single-file operations (×3) | **5** | 3 | 2 | 1 |
| Metadata filtering (×2) | 4 (SQL join) | **5** | 2 | 5 |
| Scale fit ≤ 500k vectors (×2) | **5** | 5 | 5 | 5 |
| Maturity (×1) | 3 | 5 | 5 | 4 |
| **Weighted total (max 55)** | **48** | 35 | 33 | 29 |

## 5. News ingestion path (ADR-002)

| Criterion (weight) | **GDELT + whitelist crawler** | GDELT + Finnhub | Chinese media + translation |
|---|---|---|---|
| Cost (×2) | **5** | 4 | 2 |
| English coverage (×2) | **4** | 5 | 1 |
| Extensibility to Chinese sources (×2) | **5** (crawler path, FR-024) | 2 | 5 |
| API surface count (×1) | **4** | 3 | 3 |
| **Weighted total (max 35)** | **28** | 23 | 15 |

## 6. Structured store (ADR-003)

| Criterion | **SQLite (WAL)** | DuckDB + parquet | PostgreSQL |
|---|---|---|---|
| Single-user local fit | **5** | 4 | 1 |
| Operational simplicity | **5** | 4 | 2 |
| Analytics readiness | 3 | 5 | 4 |
| Transactional consistency with vector store | **5** (same file) | 2 | 3 |
| **Total** | **18** | 15 | 10 |

## Summary of decisions

| Area | Decision | ADR |
|---|---|---|
| Agent runtime | Self-built lightweight loop | ADR-001 |
| Topology | In-process package behind facade | ADR-001 |
| Commercial source | EODHD (tier upgrade on sustained throttling) | ADR-002 |
| News | GDELT + whitelist crawler | ADR-002 |
| Vector store | sqlite-vec | ADR-003 |
| Structured store | SQLite (WAL, single file) | ADR-003 |
