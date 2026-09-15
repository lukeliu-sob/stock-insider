# ADR-003 — Storage and Vector Store

| Field | Value |
|---|---|
| ID | ADR-003 |
| Status | Accepted |
| Date | 2026-09-15 |
| Registry baseline | `docs/req/requirements.yaml` v0.3.1 |
| Governs | `data/store` module; FR-003 (retention), FR-004 (watchlist), FR-007 (retrieval), QA-003 |
| Related | ADR-001 (topology); `evaluation-table.md` (candidate scoring) |

## 1. Decision

- **Structured store: SQLite** (WAL mode; single file `data/stockinsider.db`) holding market data, fundamentals, news metadata and full text, events, the sessions index, the symbol map, and the watchlist.
- **Vector store: sqlite-vec** extension — news embeddings live in the same SQLite file, joined against the news table for metadata filtering.

Rationale: single-file operations and backup; unified retention and scheduling (one backup/VACUUM path — owner's stated preference for unified database maintenance); zero heavyweight dependencies; brute-force KNN is millisecond-class at our scale (≤ ~500k vectors over a 2-year retained corpus).

## 2. Alternatives Considered

| Candidate | Verdict | Reason |
|---|---|---|
| chromadb | Rejected | Dependency weight (implicit onnx-family pulls unless carefully pruned); a second persistence engine to operate; HNSW performance unnecessary at our scale. |
| faiss | Rejected | Index-file management plus manual metadata handling; library-grade, not store-grade. |
| DuckDB + parquet | Deferred to option ledger | Analytics-first; premature before quant workloads exist (FR-025 reopen path). |
| PostgreSQL + pgvector | Rejected | Violates the in-process, single-user deployment shape (blueprint §2). |

## 3. Consequences

**Positive**: one backup artifact; transactional consistency between news metadata and embeddings; minimal dependency set (course CI stays fast).

**Negative / accepted**: sqlite-vec is younger than chromadb — mitigations: pinned extension version plus a KNN-path regression test (QA-002 suite); brute-force KNN cost grows linearly with corpus size (bounded by the 2-year retention policy).

## 4. Reopen Conditions

- Corpus scale or query latency outgrows brute-force KNN (sustained retrieval complaints; QA-002 misses with a plausible index cause).
- Extension portability breaks on target platforms.
- Quant workloads (FR-025 reopen) demand columnar analytics → the DuckDB option-ledger entry activates.
