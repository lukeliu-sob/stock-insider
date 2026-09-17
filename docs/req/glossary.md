# Glossary — Stock Insider

> Deliverable D1 (companion to `requirements.yaml`). Single source of
> terminology for all requirements, architecture artifacts, code, and
> agent output.
>
> **Rules** (per agent-era RE methodology):
> 1. One term, one meaning. Requirements writing may only use terms defined here.
> 2. Every term maps to a code constant, table, or module — no free-floating vocabulary.
> 3. New terms enter through a requirement change; stale terms are
>    deprecated (never silently deleted) per the retirement protocol.
> 4. Language policy: English only (`REQ-SI-GOV-001`). The sole exception
>    is documented in the *Alias* entry below.

## Terms

| Term | Definition | Code mapping |
|------|------------|--------------|
| Session | The single unit of conversation and traceability: one folder per session, multi-turn by definition (subcommand or REPL). Lifecycle: open → active → closed; a closed session can be resumed — new turns are appended, prior turns never rewritten. Follow-up questions are ordinary turns within a session. | `sessions/<session_id>/`; `sessions` index table; `SessionManager` |
| Analysis Profile | User-selectable analysis tier: `quick`, `standard`, `deep`, chosen at session start and fixed for the session lifetime (switching requires a new session). Governs context budget, retrieval depth, tool-pass limit, and model routing. Default: `standard`. | config `profiles`; `SessionRecord.profile` (`REQ-SI-FR-020`) |
| Authority Boundary | The rule that LLM output is advisory while deterministic code (tools, guardrail) is authoritative; the tool registry is the membrane between the two. | blueprint §6; `agent/registry` |
| Backfill | Fetching missing historical bars for a symbol (5-year horizon), triggered on watchlist addition or gap detection. | `IngestionService.backfill` |
| Benchmark Index | Built-in index whose returns serve as the baseline for abnormal-return computation: HSI, HSTECH, S&P 500, Nasdaq-100. | `benchmarks` config; `market_data` rows (index symbols) |
| Canonical Symbol | The internal security identifier: `US:<ticker>` or `HK:<4-digit code>`, e.g. `US:AAPL`, `HK:0700`. All storage, retrieval, and output use canonical symbols. | `symbol_map` table |
| Compaction | The reduction of the conversation-history layer (L4) into the session summary (L5) when assembled context reaches the compaction threshold (default 80% of the profile budget) or on `/compact`. Critical constraints and the provenance ledger are re-injected afterward. | `agent/context` (ADR-001 §6.3–6.4) |
| Context Snapshot | The manifest of every data record that entered a response's model context — one snapshot per assistant response. Basis for post-check verification and session review. | `sessions/<session_id>/context/` |
| Context Assembly | The deterministic pipeline that builds each model prompt: deduplicate → prioritize by layer → budget by profile → compact → assemble → re-inject critical constraints. | `agent/context` (full design in the ADR) |
| Data Gap | A difference between exchange-calendar trading days and stored bars for a symbol over the horizon. | `IngestionService.detect_gaps` |
| Egress Whitelist | The closed set of endpoints the system may contact (chat/embedding providers, data sources); enforced at a single HTTP-client choke point. | `shared/net` (`REQ-SI-SEC-003`) |
| Embedding | A dense numeric vector representation of text produced by an embedding model; the basis of semantic news retrieval — similar meaning maps to nearby vectors. Data-side infrastructure, not an agent capability. | sqlite-vec vectors in `data/stockinsider.db`; embedding provider config (`REQ-SI-FR-021`) |
| Event Score | Structured LLM judgment on a news item's market relevance: direction (`positive`/`neutral`/`negative`), strength (1–5), confidence (0.0–1.0), one-sentence rationale. Scale locked for v1. | `events` table; `EventScorer` (`REQ-SI-FR-009`) |
| Event Study | Deterministic computation of forward and abnormal returns over T+1 / T+5 (primary) / T+20 trading-day windows around scored events, aligned to the exchange calendar. | `EventStudy.compute` (`REQ-SI-FR-010`) |
| Evaluation Set | Fixed, version-controlled query–answer corpus replayed by the semantic evaluation gate on any prompt or model change. | `eval/` corpus; gate in CI (`REQ-SI-GOV-003`) |
| Faithfulness | Fraction of answer claims supported by retrieved context. Quality metric for RAG answers. | `REQ-SI-QA-001`; eval harness |
| Fit Criterion | The machine-checkable completion rule for a requirement: test rule + threshold + verification method. | registry field `fit_criterion` |
| Incomplete Turn | A turn interrupted before its post-check completed; marked `incomplete` in session.jsonl and excluded from context reconstruction on resume. | `agent/session` (memory-design §3) |
| Model Routing | The per-profile, per-role mapping of model roles (chat, reasoning, event scoring, embedding) to configured models. Default for all roles and profiles: `deepseek-flash`; user-overridable per profile. | config `profiles.*.models` (ADR-001 §6.5) |
| News Relevance Filter | Ingestion-time filter admitting only news relevant to active watchlist symbols or macro keywords. No firehose ingestion. | `IngestionService.filter_news` (`REQ-SI-FR-003`) |
| Post-check | Deterministic verifier that extracts numerics from final agent output and matches each against the run's context snapshot. Executor of `REQ-SI-INV-001`. | `Guardrail.postcheck` |
| Profile Budget Envelope | The per-session token ceiling bound to the analysis profile. Overflow: compact-and-retry once per response, then explicit abort. | config `profiles.*.budget` (`REQ-SI-COST-001`) |
| Provenance Ledger | A compact digest of every data record used in a session (record IDs + value hashes), maintained by the context assembler and re-injected after every compaction. Architecturally non-compactable — the comparison basis of the INV-001 post-check in long sessions. | `agent/context` (ADR-001 §6.4) |
| Provenance Type | Data-origin tag on every stored record and cited fact: `api`, `crawled`, `computed`, or `model-judgment`. | record field `provenance` |
| Provider | A user-configured OpenAI-compatible endpoint: one for chat, one for embedding. Provider and model identifiers stamp every run record. | config `providers` (`REQ-SI-FR-021`) |
| Quant Model | A locally trained classical machine-learning model (gradient-boosting / regression class) for statistical research on retained data. Distinct from LLM/embedding providers, which are API-only per `REQ-SI-FR-021`. | `data/quant` (`REQ-SI-FR-025`) |
| Session Review (show) | Read-only rendering of a session: turn-by-turn transcript, tool calls, per-response context records, report artifacts, post-check verdicts. | CLI `show` (`REQ-SI-FR-022`) |
| Slash Command | A REPL-internal command (e.g. `/resume`, `/compact`, `/tools`) mapped one-to-one onto CLI subcommands or session-internal operations; never a third verb set. | `agent/repl` (`REQ-SI-FR-013`) |
| Symbol Resolution | Verified lookup of a user-mentioned security against the provider symbol search API, producing a canonical symbol candidate for user confirmation. Watchlist addition is impossible without it. | `SymbolResolver.resolve` (`REQ-SI-INV-004`) |
| Sync | Idempotent daily ingestion job: market data, fundamentals, news. Detects and repairs gaps; reports failures explicitly. | CLI `sync` (`REQ-SI-FR-001`) |
| Test Plan | A version-controlled artifact (`docs/test-plans/TP-NNN.md`) describing a change's tests, approved before implementation begins; implementation PRs must reference it and the approval gate validates the reference. | `docs/test-plans/` (`REQ-SI-GOV-006`) |
| Tool Registry | The single catalog of runtime agent tools: name, input schema, output schema, provenance stamping rule, failure semantics. The only channel between the agent and the data side. | `agent/registry`; schemas in `shared/` |
| Values-as-Seen | Snapshot discipline: context snapshots store the actual values that entered the model context, not references alone; later data changes never alter past audit records. | `sessions/<id>/context/` (`REQ-SI-FR-011`) |
| Watchlist | The set of active canonical symbols under tracking, capped at 100. Basis for ingestion scope and news filtering. | `watchlist` table (`REQ-SI-GOV-004`) |
| Whitelist Crawler | Optional fetch tool restricted to configured financial-media domains, with per-domain extraction templates and schema validation. | `Crawler` (`REQ-SI-FR-015`) |
| Alias | The sole permitted non-English content: Chinese stock names stored as aliases in `symbol_map` (e.g. `HK:0700` ↔ `腾讯控股`). Aliases never appear in reports outside the alias-table context. | `symbol_map.aliases` (`REQ-SI-GOV-001`) |

## Pending terms (defined at architecture time)

| Term | Why pending |
|------|-------------|
| Safe-list (post-check) | Mechanism for non-data numerics (e.g. years) inside the INV-001 post-check — defined with the Guardrail design. |
| Session transcript | Field-level schema of `session.jsonl` — fixed when the session persistence module is designed. |
