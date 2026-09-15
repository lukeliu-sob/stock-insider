# Option Ledger — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/architecture/option-ledger.md` (course deliverable D2.11, optional — maintained) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Related | ADR-001/002/003; `evaluation-table.md` |

Rejected or deferred options and the conditions under which they are reconsidered. An option leaves this ledger only by an explicit ADR reopening it.

| Option | Status | Why rejected/deferred | Reconsider when | Reference |
|---|---|---|---|---|
| Agent frameworks (LangGraph / pydantic-ai / smolagents) | Rejected | hide the context pipeline the course requires us to govern; dependency lock-in | a framework offers verifiable guardrail hooks + enforceable budgets we cannot replicate cheaply | ADR-001 |
| Local service topology for the data side | Rejected | daemon failure modes with no consumer for a single-user CLI | multi-user / remote access becomes a requirement | ADR-001 |
| LLM-generated SQL data access | Rejected | violates INV-001/003 and SEC-002 layered defense | never (invariant-level) | ADR-001 |
| Broker OpenAPIs (Futu / Tiger / IBKR) | Rejected (reopenable) | resident gateway process; quotas; ToS verification burden | owner acquires a brokerage account; economics change | ADR-002 |
| Tushare Pro | Rejected | HK fundamentals coverage insufficient at acceptable tiers | coverage materially improves | ADR-002 |
| Polygon / FMP as fundamentals source | Rejected | HK coverage weak, fails FR-002 criterion | HK coverage becomes core strength | ADR-002 |
| Finnhub (news) | Dropped | GDELT + crawler covers the need with fewer API surfaces | GDELT coverage gaps for US company news prove material | ADR-002 |
| chromadb | Rejected | dependency weight; second persistence engine; HNSW unnecessary at scale | scale/latency reopen (R-04) | ADR-003 |
| faiss | Rejected | index-file management; manual metadata; library-grade not store-grade | same as chromadb | ADR-003 |
| PostgreSQL + pgvector | Rejected | violates in-process single-user shape | multi-user serving requirement | ADR-003 |
| DuckDB + parquet | Deferred | analytics-first; premature before quant workloads | FR-025 reopen (quant models demand columnar analytics) | ADR-003, FR-025 |
| Keyword-search fallback for retrieval | Rejected | silent quality degradation when vector index unavailable | never as silent path; an *explicit* labeled fallback could be proposed via ADR | P-04 |
| Real-browser bridge (web reading tier C) | Won't | agent/user identity conflation; violates egress whitelist model | never under current security posture | blueprint §9.4 |
| Headless-browser fetching (tier B) | Deferred (Could) | heavy dependency; JS rendering not yet required | a whitelisted source becomes unreadable without rendering | blueprint §9.4 |
| Local quant model training | Deferred (FR-025, future) | dependencies, backtest-overfitting governance, INV-002 tension | event-study stats ≥ 6 months and hit-rate significantly above random baseline | FR-025 |
| Chinese news sources + translation pipeline | Deferred (FR-024, Could) | cost and translation-fidelity risk under English-only policy | owner prioritizes Chinese-language HK coverage | FR-024 |
| Auto-add watchlist symbols without confirmation | Rejected | violates INV-004 human-in-the-loop | never (invariant-level) | INV-004 |
| Intraday data / trading execution / social media / multi-user | Won't (this version) | scope decisions recorded in registry meta | explicit owner scope change via registry | registry meta |
