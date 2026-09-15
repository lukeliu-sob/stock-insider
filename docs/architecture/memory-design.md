# Memory and State Design — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/architecture/memory-design.md` (course deliverable D2.5) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Registry baseline | `docs/req/requirements.yaml` v0.3.1 |
| Related | `architecture-blueprint.md` §7, §11; ADR-001; ADR-003 |

What state survives across sessions, interruptions, and versions; who may write and read it; how long it is kept; what is private. Policies below were owner-confirmed (R8).

## 1. State Inventory

| # | State | Storage | Sole writer | Retention | Rebuildable |
|---|---|---|---|---|---|
| S1 | Domain data: market bars, fundamentals, news, events, symbol map, watchlist | SQLite (`data/stockinsider.db`) | `data/ingest` (incl. tool write-gates) | see §2 | no — external facts |
| S2 | Session state: `session.jsonl`, per-turn artifacts, context snapshots, sessions index | `sessions/<session_id>/` + index table | `agent/session` | indefinite (audit trail) | no |
| S3 | Configuration: providers, profiles, egress whitelist, crawler domains | config files (schema-versioned) | user via `config` command | indefinite; forward-only migrations | manually |
| S4 | Runtime prompts | `prompts/` (in-repo, versioned) | prompt-change flow (GOV-003) | all versions retained | no |
| S5 | Derived state: vector index, sync cursors, gap-repair queue | inside SQLite | owning module | follows S1 | **yes** (vector index = news corpus × embedding model) |
| S6 | Schema/format versions: DB schema, session format | version fields + migration table | migration mechanism | forward-only | — |

Single-writer rule: each state class has exactly one writer; everything else reads. The LLM never writes any state class directly (blueprint §4.1).

## 2. Retention Decisions (owner-confirmed)

1. **Market bars: retained forever.** The 5-year figure in FR-001 is the backfill minimum window, not a pruning horizon; storage volume is trivial.
2. **News: full text and embeddings expire at 2 years** (FR-003 auto-expiry). **Event scores are retained indefinitely** together with a headline snapshot and source URL — they are the cumulative research asset behind event studies (FR-010) and the QA evidence base.
3. **Vector index rebuild rule:** the index carries an embedding-model identifier. Changing the configured embedding model **requires a full index rebuild**; mixed-model vector spaces are forbidden (similarity scores across different embedding spaces are meaningless). Rebuild is deterministic and offline-runnable.

## 3. Interruption Policies

| Scenario | Policy |
|---|---|
| Crash during sync | Transactional: no partial writes; the gap is recorded; the next `sync` retries (runtime policy P-02). |
| Crash mid-turn | The partial turn is written with status `incomplete`; **a turn counts as complete only after its post-check has run**. `resume` continues from the last complete turn; incomplete turns are excluded from context reconstruction (glossary: *Incomplete Turn*). |
| Provider outage mid-session | The turn aborts with an explicit error; partial usage is recorded; the session stays resumable (P-05). |
| Process kill during migration | Migrations run in a transaction; failure leaves the previous schema version intact. |

## 4. Cross-Version State

- **DB schema**: versioned via migration table; forward-only; old code never opens newer schemas (explicit version error, not silent misread).
- **Session format**: `session.jsonl` carries a format-version field; new code must keep reading older formats (backward compatibility of `show`/`resume` — risk R-10 tracks this).
- **Configuration**: schema-versioned; migrations explicit and logged.

## 5. Privacy

- All state is local; zero telemetry.
- The only external exposure is inherent: provider APIs see the prompt content they are sent (query + retrieved context). No secrets, session files, or databases ever leave the machine.
- `.env` and local untracked configuration are unreadable by the coding agent (permission model).

## 6. Traceability

Implements: FR-003 (retention), FR-011 (session persistence, values-as-seen), FR-023 (resume), GOV-005 (stamps), SEC-003 (local-only). Referenced by the trace matrix for those requirements.
