# Bug Diary — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/bug-diary.md` (course deliverable D4) |
| Discipline | One entry per significant bug: symptom, reproduction, classification, root cause, fix, and the invariant/process gap it exposed. Pre-implementation entries below are process-phase incidents — they seeded the discipline before any code existed. |

## Entry template

```
## BD-NNN — <title>
Date / discovered by (human review | AI self-check | CI gate):
Symptom:
Reproduction:
Classification (methodology §7.1/§7.2 item, or process):
Root cause:
Fix:
Invariant/process gap exposed → what changed:
```

## Entries

## BD-001 — Registry bulk edit swallowed entry fields
- **Date / discovered by**: 2026-09-15 / CI-style self-check (schema gate run after edit)
- **Symptom**: after a multi-block edit, `REQ-SI-FR-011` failed schema validation (`status` missing).
- **Reproduction**: apply a block replacement whose oldText spans trailing fields; the replacement drops them silently.
- **Classification**: process — tooling incident; attention-adjacent (§7.2 A-4 in spirit: constraints/fields lost in bulk operations).
- **Root cause**: large-surface text edits without an immediate post-edit validation run.
- **Fix**: restored fields; re-ran full validation.
- **Gap exposed → change**: rule adopted — every registry edit is followed immediately by the schema gate before any other work continues (now encoded as CI `structural` job on every commit).

## BD-002 — Trace-matrix combined-row coverage miss
- **Date / discovered by**: 2026-09-15 / validation script
- **Symptom**: PERF-002/003 written as one combined row (`PERF-001/002/003`) evaded per-ID coverage checking.
- **Reproduction**: regex `\b(?:...)-\d{3}\b` matches only the first ID in a slash-combined form.
- **Classification**: §7.2 A-5 in spirit (traceability loss through formatting).
- **Root cause**: matrix rows not written one-ID-per-row; checker accepted the omission until per-ID comparison was enforced.
- **Fix**: split into three rows; checker now compares ID sets exactly.
- **Gap exposed → change**: verification rule R1 hardened — coverage check is per-ID set equality, and matrix rows must list IDs individually.

## BD-003 — YAML colon parsing trap in registry meta
- **Date / discovered by**: 2026-09-15 / schema gate
- **Symptom**: a scope line became a nested mapping (`{'Session persistence': '...'}`) instead of a string; validation failed on type.
- **Reproduction**: unquoted `- Key: value` list item.
- **Root cause**: YAML colon-space semantics; no linting at write time.
- **Fix**: quoted the line.
- **Gap exposed → change**: schema gate validates the `meta` block shape on every commit (it already caught this class once — the fix is its continued enforcement, plus the convention: quote any list item containing a colon).

## BD-004 — Dangling cross-reference in ADR-001
- **Date / discovered by**: 2026-09-15 / AI self-review during follow-up authoring
- **Symptom**: ADR-001 referenced "AILOG-0001 through AILOG-0007" when only five sessions existed.
- **Reproduction**: forward-referencing a predicted future state in prose.
- **Classification**: §7.2 A-5 (provenance/trace loss).
- **Root cause**: cross-file references written by prediction instead of by lookup.
- **Fix**: reference replaced with a stable pointer to the log file.
- **Gap exposed → change**: DE-06 opened — cross-file reference linting is deferred debt with a repayment trigger.

## BD-005 — Role confusion in AGENTS.md non-negotiables
- **Date / discovered by**: 2026-09-15 / **human review (owner)**
- **Symptom**: AGENTS.md §2 presented product-runtime invariants (INV-001..004) as if they directly bound the coding agent reading the file.
- **Reproduction**: dual-audience document written without explicit audience framing.
- **Classification**: §7.1-5 (ambiguity) + human-oversight value case.
- **Root cause**: AGENTS.md serves two audiences (coding agent now, product constraints being implemented); the section mixed what binds the reader with what binds the artifact being built.
- **Fix**: §2 split into 2a (development rules binding the coding agent) and 2b (product invariants framed as constraints on generated code); companion framing notes in §3/§7; full-repo audit found no other instance.
- **Gap exposed → change**: dual-audience artifacts require explicit audience declarations (added to review-memo spec-alignment checklist); recorded as AILOG-0009 — a concrete instance of human oversight catching what the agent did not.

## BD-006 — Worktree modifications silently reverted post-commit (external process)
- **Date / discovered by**: 2026-09-16 / CI gate (aiuse, quality, regression failed on PR #1)
- **Symptom**: a change set committed as complete arrived on CI missing four files (ci.yml guard removal, CODEOWNERS owner fix, debt-register DE-05 update, AI-log AILOG-0013); local worktree later showed the files reverted to pre-change content with fresh mtimes, while byte-level validation had passed immediately after application. A `tools/checks/testplan_gate.py` patch was reverted the same way in a later round.
- **Reproduction**: modify any already-tracked file (new/untracked files are untouched); after a delay of seconds to minutes the content reverts to the git HEAD version; timing is intermittent (a probe marker survived 6 s in one window).
- **Classification**: process — environment/tooling incident (not agent methodology §7.1/§7.2: the agent's edits were correct and validated; the loss occurred after validation).
- **Root cause**: unidentified external process on the development machine reverting tracked-file modifications (candidates: cloud-sync/backup agent on the repo path, editor auto-restore of stale buffers, or similar). Not a defect of the agent, the gates, or git.
- **Fix**: atomic apply→stage→verify-staged-bytes→commit→push in a single shell invocation, so the commit captures verified content before any revert window opens. CI confirmed the completed change set green on all six contexts.
- **Gap exposed → change**: (1) local pre-push verification must validate the STAGED content (`git diff --cached`), not just the worktree; (2) the environment issue must be identified and eliminated by the owner — until then the atomic-commit discipline stands; (3) the incident doubles as evidence that the change-set gates (D7-5/D7-6) catch incomplete change sets that local worktree checks can miss.

## BD-007 — In-REPL /resume orphaned the current session
- **Date / discovered by**: 2026-09-17 / owner live-use feedback ("not intuitive")
- **Symptom**: /resume inside the REPL swapped the binding without closing the current session — it stayed `active` in the index forever, with no REPL command able to close it; bare /resume also jumped to an unexpected (most-recent-closed) target.
- **Reproduction**: open a session, /resume another closed session, /exit — the first session remains active in `sessions` listing.
- **Classification**: process — usability defect in session lifecycle semantics (design gap in TP-007b's in-place swap).
- **Root cause**: binding-swap implemented without lifecycle ownership transfer; no close operation existed in the REPL loop.
- **Fix**: close-current-then-bind (owner ruling, option A): resolve target first, refuse self-resume, close the current session cleanly, then bind; exit hints added to both REPL entries.
- **Gap exposed → change**: in-REPL session-switching now has an explicit lifecycle rule; exit hints make the CLI resume path discoverable. Two new tests pin the semantics.

## BD-008 — Default model name did not exist in the live endpoint catalog
- **Date / discovered by**: 2026-09-17 / owner first live conversation (HTTP 400)
- **Symptom**: free-text turn failed with `The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed deepseek-v4.1-flash.`
- **Reproduction**: any chat turn with defaults and no PROVIDER_CHAT_MODEL/config override.
- **Classification**: §7.2-adjacent process — requirement-era assumption never validated against the live API (the registry's named default was aspirational).
- **Root cause**: decision-time model name baked into code defaults, docs, and registry-adjacent artifacts without a live catalog check; CI eval masked it where a PROVIDER_CHAT_MODEL secret override existed.
- **Fix**: defaults corrected to deepseek-flash (PR #10) with marked-not-silent doc corrections (ADR-001 note, TP-003 amendment, evalbook note); layered config covered users immediately with zero code change.
- **Gap exposed → change**: provider-dependent defaults should be verified against the live catalog at first integration (a "smoke the default" live check belongs in the eval set — noted as a candidate case).

## BD-009 — Resolver ignored the env-file key and never wired its live transport
- **Date / discovered by**: 2026-09-18 / owner live use ("set the key in the dotenv file, why is it not read")
- **Symptom**: `watch add` failed with "symbol search is not configured: set EODHD_API_KEY" even with the key correctly placed in the local dotenv file — and, worse, would have failed the same way with a real environment variable.
- **Reproduction**: any `watch add <mention>` after TP-008, regardless of key configuration.
- **Classification**: process — misleading error text plus a test blind spot: every offline test injected a fake transport, so CI stayed green while the end-to-end live path was dead.
- **Root cause**: dotenv parsing lived only in the provider path (agent/providers) and the data-side resolver read real env only; DataStore constructed SymbolResolver without any transport default; the single error message masked both gaps.
- **Fix**: shared/envfile.py (dotenv reading as a shared concern, real env wins, ADR-004 governance); resolver resolves the key from env OR file and auto-wires the stdlib transport when a key exists; is_live() probe; CLI tests isolate the env-file lookup; new test_envfile.py suite pins parsing, precedence, wiring, and the explicit-unavailable path.
- **Gap exposed -> change**: (1) any externally-facing "not configured" error must name every accepted configuration source; (2) wiring defects of this class are caught only by a default-construction test — one now exists; (3) providers' dotenv reader should migrate onto shared/envfile (DE-07).

## BD-010 — Egress whitelist pinned a nonexistent EODHD host
- **Date / discovered by**: 2026-09-18 / owner live use (first live resolver call)
- **Symptom**: `watch add` raised `EgressViolationError: host 'eodhd.com' not in whitelist; allowed: ['api.eodhd.com', ...]` — the resolver URL (correct) was blocked by a whitelist entry (wrong).
- **Reproduction**: any live EODHD call after BD-009.
- **Verification**: live probes both directions — `https://eodhd.com/api/search/...` returns 403 (host serves the API; 403 is the demo-token refusal), `https://api.eodhd.com` fails to connect (host does not exist).
- **Classification**: process — second instance of the BD-008 family: a decision-era vendor assumption never verified against the live endpoint. The egress gate itself worked exactly as designed (it blocked the first wrong-host attempt — S2 evidence).
- **Root cause**: the whitelist constant was authored from an assumed `api.`-subdomain convention; EODHD's API host is the apex domain (`eodhd.com/api/...`).
- **Fix**: whitelist `api.eodhd.com` -> `eodhd.com`; five pinned test assertions synced (subdomain allowance now `data.eodhd.com`; suffix-attack case now `eodhd.com.evil.example`); GDELT entry verified correct and unchanged. The legacy alias host `eodhistoricaldata.com` also serves but stays off the whitelist (minimal set; noted for the record).
- **Gap exposed -> change**: vendor-credential artifacts (hosts, endpoints, model names) get one live smoke at first integration; BD-008's "smoke the default" candidate now extends to "smoke the host" — folded into the TP-009 live checklist.
