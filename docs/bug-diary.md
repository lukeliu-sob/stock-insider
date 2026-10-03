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

## BD-011 — Benchmark index symbols used a wrong suffix (.IND, not .INDX)
- **Date / discovered by**: 2026-09-18 / owner live sync (first ingestion run)
- **Symptom**: all four benchmark backfills failed with HTTP 404; nothing ingested; the report listed per-symbol failures explicitly (the INV-003 path worked as designed).
- **Investigation path (recorded for the report)**: demo-token probes suggested the symbols existed (403), which was a red herring — demo returns 403 for every non-demo symbol including nonexistent ones (verified with a garbage ticker); the paid key returned 404; the exchanges list has no IND exchange; the HK ticker list contains only index-tracking ETFs; the vendor's index-constituents blog post revealed the true suffix in an example — `GSPC.INDX`. All four benchmarks then verified live (HSI/HSTECH through the current HK session).
- **Classification**: process — fourth instance of the BD-008 family (decision-era vendor assumption never verified against the live endpoint). The mid-round purchase recommendation ("All World covers indices") was itself an unverified assumption; the subscription turned out unnecessary for THIS failure (though needed for scale — 100k calls/day) and the real fix is the suffix.
- **Root cause**: benchmark seed constants were authored from recollection of a `.IND` convention; EODHD uses `.INDX`.
- **Fix**: seeds/calendar map/currency map/tests switched to `.INDX` (21 occurrences); stale `.IND` seed rows in existing databases are inert (INSERT OR IGNORE reseeds the correct four); sync smoke checklist extended — "smoke the symbol" joins host/default/row-shape.
- **Gap exposed -> change**: vendor CONSTANT artifacts (symbols, hosts, model names, endpoints) now get a mandatory live probe at first integration, no exceptions; the probe evidence lives in the AI-log entry that introduces them.

## BD-012 — Postcheck exact-match flagged display-rounded citations (false positive)
- **Date / discovered by**: 2026-09-21 / owner live use (first conversational quote question)
- **Symptom**: the model answered with tool-returned prices rounded to two decimals (24,879.24 for a pool value of 24879.2402); the postcheck quarantined the response ("data unavailable for: 24748.45 ...") — a correctly-cited number rejected, violating INV-001's "correctly cited numbers must pass in 100 percent of cases".
- **Investigation**: offline repro with clean literals PASSED — the algorithm was right; the on-disk values-as-seen snapshot revealed the four-decimal vendor values (indices and adjusted closes) and the model's two-decimal rendering.
- **Classification**: process/design gap — the exact-match spec predates contact with real four-decimal data; "display rounding" and "fabrication" were indistinguishable to the check.
- **Root cause**: models humanize numeric rendering; vendor precision exceeds display precision; exact match has no rendering-convention allowance.
- **Fix**: display-rounding match — a token with exactly d decimals (d in 2..4) matches a pool value within half an ulp of that decimal place, tracked as `rounded` for audit; integer-scale deviations (the ±1 adversarial class) still fail (tokens with 0 or 1 decimals never display-round-match; the bound shrinks with d; truncation attacks like ...241 against ...2402 exceed the d=3 bound). identity.md v2 -> v3 adds "Numbers render as returned" (belt-and-braces; GOV-003 eval replay). ADR-006 amendment; invariants INV-001 note.
- **Gap exposed -> change**: the invariant's first live contact — the check did its job by refusing an unaudited transformation; the refinement makes the allowance explicit and bounded rather than implicit. Any future matching relaxation must carry its own adversarial suite.

## BD-013 — GDELT throttle misclassified at the transport seam
- **Date / discovered by**: 2026-09-23 / owner live test (first live news sync)
- **Symptom**: a fully throttled run classified every failure as `transport` (and one as `malformed`), so the throttle-abort logic never fired: all queries were attempted, and the cursor advanced past unsynced data.
- **Investigation**: the stdlib seam raises `TransportError` for non-200 responses instead of returning a `FetchResult`; the adapter's `status == 429` branch was unreachable. Separately, one query returned HTTP 200 with an empty body — GDELT's soft-throttle form — which fails JSON parsing and looked `malformed`.
- **Classification**: integration bug across a module seam + an unknown vendor behavior (the BD-008..011 family: a vendor-constant assumption corrected by live fire).
- **Fix**: the transport-exception path recovers the status from the message (`429` -> throttle); an empty 200 body raises `throttle` explicitly (an empty artlist is never valid JSON, and misclassifying it would advance the cursor past unsynced data). The CLI `sync` rendering now shows the news track (the report carried it; the surface dropped it — INV-003 visibility).
- **Gap exposed -> change**: throttle semantics must be tested at the seam level, not only against status codes — a stub returning FetchResult(429) exercises a path the live stdlib transport never takes. The failure taxonomy tests now cover both seam shapes.

## BD-006 — Worktree "reverter" root cause identified (correction)

- **Date / corrected**: 2026-09-29 (original entry 2026-09-14; root cause was recorded then as "unknown external process" — that was wrong).
- **Root cause (identified by the second external audit, confirmed locally)**: the local pi harness extension `~/.pi/agent/extensions/git-safety.ts` stashes and restores the worktree every turn ("pi-turn" stashes; 30 accumulated), and `.git/AUTO_MERGE` artifacts from merges over a dirty worktree replayed pre-merge content into tracked files (mtime-identical to the merge moment). Every "file reverted mid-build" event in AILOG-0040..0053 traces to this mechanism — not to any external actor.
- **Disposition (2026-09-29)**: extension disabled (renamed `.disabled`), the 30 stashes archived by SHA to `.git/stash-archive-20260929.txt` and cleared, worktree verified byte-identical to origin/main. The git-staging build discipline (`.git/tpXXX/` + `checkout-index` export) that all subsequent work used remains the correct defense-in-depth even with the harness fixed.
- **Lesson**: an agent fighting "sabotage" for a week should have hunted the sabotage INSIDE its own harness first; the harness is part of the system under test.

## BD-014 — SyncReport.as_dict dropped the news field
- **Date / discovered by**: 2026-09-24 / agent during live news verification.
- **Symptom**: `stockinsider sync` and the `sync.run` tool output carried no news track although the news sync ran and stored rows.
- **Investigation**: `SyncReport.as_dict` — the sole rendering surface for both CLI and registry tool — omitted the `news` attribute added in TP-011b; both surfaces dropped the track silently (an INV-003 visibility defect, not a data defect).
- **Classification**: representation bug at a single serialization point.
- **Fix**: one line (`news`) in `as_dict` + a regression test pinning the field's presence on both surfaces.
- **Gap exposed -> change**: new report fields need a serialization test at the seam that owns rendering, not just the producer.

## BD-015 — Postcheck flagged percent-converted citations (false positive)
- **Date / discovered by**: 2026-09-25 / first live indicator report.
- **Symptom**: the report cited 0.18573119602909305 exactly, then added "about 18.57%" — quarantined.
- **Investigation**: percent conversion (pool x 100) was accepted only for bare equal renderings; a rounded percent with an adjacent marker is the same number in display convention.
- **Classification**: guardrail matching-semantics gap (BD-012 family).
- **Fix**: token = pool*100 within half-ulp of a 1-4dp rendering qualifies only when a %/percent/pct marker is adjacent; bare numbers never qualify. Adversarial negatives pin the edges (identity v4, ADR-006 Amendment 2).

## BD-016 — Line-leading enumeration ordinals extracted as numerics
- **Date / discovered by**: 2026-09-26 / first live /report.
- **Symptom**: "Known gaps" numbered 1. 2. 3. — the ordinals were extracted as numeric claims and quarantined the whole report through regeneration.
- **Classification**: extraction-shape gap (layout markers vs data numerals).
- **Fix**: line-leading enumeration markers (1-3 digits + . or ) + whitespace) strip before extraction. Residual classes deliberately NOT patched (inline enumerations, identifier fragments) — recorded for the owner extraction-semantics decision; ADR-006 Amendment 3.

## BD-017 — EODHD /api/search does not index HK listings
- **Date / discovered by**: 2026-09-27 / live watchlist verification.
- **Symptom**: searching "Tencent" or its ISIN returns zero HKEX rows while EOD/news endpoints serve 0700.HK fine.
- **Investigation**: live probes against name and ISIN queries both empty for .HK; the search index simply does not cover the exchange.
- **Classification**: vendor coverage gap, not a defect in our seam.
- **Fix**: direct-symbol verification path (TP-015 PR-b): canonical-shaped queries verify existence with one budgeted EOD fetch; display name honestly "name unverified"; INV-004 confirmation unchanged.

## BD-018 — ISO date citations fragmented by the extractor
- **Date / discovered by**: 2026-09-27 / live news-analysis turn.
- **Symptom**: fully-cited analysis quarantined with dozens of `-09`/`-23` tokens: the model rendered ISO dates (2026-09-23) while the pool carries compact seendates (20260923).
- **Classification**: rendering-convention mismatch (BD-012/015/016 family).
- **Fix**: a 4-2-2 ISO calendar date folds to compact YYYYMMDD on both sides (candidate and pool string extraction); fabricated dates still fail (ADR-006 Amendment 4).

## BD-019 — INV-001 snapshot keyed by tool name (last-wins eviction)
- **Date / discovered by**: 2026-09-29 / comprehensive user-simulation round.
- **Symptom**: a two-quote turn quarantined the FIRST quote's citations; a seven-tool compare turn kept only the last result (its pool even rendered empty when the final call returned a non-dict).
- **Investigation**: `snapshot_values[name] = result.result` in the tool loop — same-tool repeat calls evicted earlier results from the verification pool.
- **Classification**: implementation bug in the INV-001 enforcement point (the worst kind: the invariant's checker was losing evidence).
- **Fix**: snapshot keys carry a per-call sequence (`market.quote#1`, `#2`, ...); the pool walker is key-agnostic so verification semantics are unchanged. Regression tests pin both-call citability and the fabricated-value negative.
- **Gap exposed -> change**: found only by simulation with same-tool repeat calls — added to the standing battery pattern.

## BD-020 — Identifier blanking swallowed letter-glued numerics (INV-001 bypass)
- **Date / discovered by**: 2026-09-30 / fifth external review.
- **Symptom**: "Tencent closed at HKD777." passed the post-check against a 630.5 close; so did "USD1200", "PE35", "RMB500 billion", "YTD-12%".
- **Investigation**: the TP-018b identifier rule blanked every 1-3 letters glued to 1-4 digits (and every letters-hyphen-digits run) BEFORE extraction, to stop "ADR-005" being read as -005; the fix for a false positive became a bypass of the invariant it served.
- **Classification**: enforcement-point defect introduced by a remediation (worst class: the checker stopped seeing numbers).
- **Fix**: closed set of reference shapes (governance prefixes, AmN, Q1-Q4, H1/H2, FYnn, vN, benchmark names); everything else glued to letters is checked (TP-019, ADR-006 Am8).
- **Gap exposed -> change**: remediation tests asserted only the false-positive direction; TP-019 pins the bypass direction for every blanking rule.

## BD-021 — Loopback exception matched a hostname prefix (SEC-003 bypass)
- **Date / discovered by**: 2026-09-30 / fifth external review.
- **Symptom**: `http://127.attacker.example/v1` and `https://127.0.0.1.nip.io/v1` passed egress validation, skipping both the HTTPS rule and the whitelist.
- **Classification**: security-control defect; the ADR text (127.0.0.0/8) and the review memo described the intent, the code implemented a string test.
- **Fix**: loopback = the name `localhost` or an IP literal with `is_loopback` (TP-019, ADR-004 Am4).
- **Gap exposed -> change**: the loopback test had only positive cases; TP-019 adds prefix-shaped hostnames as negatives.

## BD-022 — Regeneration request carried no question (meta-answer shown)
- **Date / discovered by**: 2026-09-30 / fifth review live run.
- **Symptom**: "Will 0700.HK go up next month?" displayed "Looks like that was my previous answer pasted back without a new question attached..." with post_check ok; the next turns referred back to that confusion.
- **Investigation**: the INV-002 regeneration sent only the stripped draft, as a USER message, with no identity prompt, question or history; nothing in session.jsonl recorded that a regeneration had happened.
- **Classification**: fallback-path defect (INV-002 §2) present since the loop landed; masked while the regeneration also streamed twice.
- **Fix**: the request replays the turn conversation, returns the draft as the assistant's, adds one harness instruction; every regeneration is recorded as an `epistemic` event (TP-019, ADR-006 Am8).

## BD-023 — History window counted events, not messages (context amnesia)
- **Date / discovered by**: 2026-09-30 / fifth review live run.
- **Symptom**: at turn 6 the model stated "no closing price appeared at the start of this conversation" although turn 1 had given 644.63.
- **Investigation**: `HISTORY_WINDOW = 20` sliced the last 20 events; with tool calls and results each turn is 5-7 events, so about three turns survived and the slice could open mid-turn.
- **Classification**: context-engineering defect (ADR-001 §6 L4).
- **Fix**: the window counts user/assistant messages, never opens on an answer without its question, and announces truncation (TP-019, ADR-001 Am1).

## BD-024 — Empty market answers reported as fresh; benchmark calendar frozen
- **Date / discovered by**: 2026-09-30 / fifth external review (offline probes).
- **Symptom**: an empty backfill reported "ok · 0 bars stored; data through <today>" and never re-planned the history; a vendor hole after the first sync was never detected.
- **Investigation**: TP-018b advanced the cursor on empty backfill/incremental answers; benchmark indices were backfilled once and never refreshed, so the calendar the completeness pass relies on stopped at the first sync.
- **Classification**: INV-003 honesty defect + FR-001 requirement gap (indices must be ingested daily).
- **Fix**: empty answers fail with the cursor unchanged; indices refresh daily at priority 1; detection stops at each symbol's cursor; closed no-data gaps stay visible (TP-019, ADR-002 Am1).

## BD-025 — AI-use log stopped being valid YAML (PR #54)
- **Date / discovered by**: 2026-09-30 / TP-019 implementation (appending AILOG-0065).
- **Symptom**: `docs/ai-use-log.yaml` no longer parsed: "expected <block end>, but found '-'" at AILOG-0063.
- **Investigation**: every entry up to AILOG-0062 is a list item indented under `sessions:`; TP-018 appended AILOG-0063/0064 at column 0. The AI-use log gate only checks that the file is in the change set, so the mandatory audit record silently became unreadable by machines.
- **Classification**: governance-record defect; gate blind spot.
- **Fix**: the two entries re-indented (whitespace only; parsed content verified identical); the gate now fails when the log does not parse or an entry id is malformed or duplicated (TP-019).

## BD-026 — Month-year and bare-year citations quarantined (prose years)
- **Date / discovered by**: 2026-10-01 / owner live session (deepseek-flash, profile standard).
- **Symptom**: "give me info about BYD" ran six tools, all ok (quote, indicators, fundamentals, news); the user saw only `data unavailable for: 2025` (post-check: failed). The whole answer was withheld, and two more such turns would have aborted the session (INV-001 three-strike rule).
- **Investigation**: `market.indicators` computes volatility and max drawdown over the last 260 stored bars, so with a year of history the window start and the drawdown peak are 2025 dates. The model rendered such a date at month or year precision ("since September 2025", "late 2025"). ADR-006 Am4/Am8 fold only FULL dates: the ledger holds 2025-09-25 as 20250925, never as a bare 2025, so the year matched nothing. Reproduced offline (TP-020 Driver table). The quarantined original is in `sessions/`, outside the agent access map, and was not read; `/show` in that session displays it.
- **Classification**: rendering-convention mismatch (BD-012/015/016/018 family). The class was already recorded as the "prose years" residual (E-005/E-006), parked for the owner extraction-semantics decision, and kept quarantining real answers meanwhile.
- **Fix**: month-years and bare years in a temporal frame are verified against the evidence calendar at their written precision; value frames stay numeric claims; unsupported references fail exactly as before (TP-020, ADR-006 Am9).
- **Gap exposed -> change**: the labeled faithfulness cases cited full dates only. TP-020 pins the live shape end to end (real `market.indicators` output through the turn engine) and pins the bypass direction (values that equal an evidence year).

## BD-027 — Terminal UI input frame stretched to the bottom of the console
- **Date / discovered by**: 2026-10-01 / AI self-check: headless real-console smoke run (ConPTY) of `stockinsider --ui tui` before the TP-021 change set was proposed; never reached main.
- **Symptom**: the framed input box ran from the prompt to the last row of the console (about 110 empty frame rows in a 120-row console), with the status line pinned at the very bottom. The sub-prompts (`select 1-N:`, `[y/N]`) had the same frame. Function was intact: completion, Tab, `/help` and Ctrl+D all worked.
- **Reproduction**: run the prompt in a console with free rows below the cursor. In tests, prompt_toolkit's DummyOutput reports 40 rows below the cursor, but its output is discarded, so the 29 TP-021 tests never inspected the stretched layout.
- **Classification**: integration defect (third-party layout behavior); test-observability gap (the rendered screen was never asserted).
- **Root cause**: a non-full-screen prompt_toolkit 3.0.53 app may use every row below the cursor. The prompt's input window has no height cap (the bottom toolbar is pinned with `dont_extend_height`), so it absorbs those rows and `show_frame` frames them. The prompt also reserves completion-menu rows whenever complete-while-typing is on.
- **Fix**: `fit_to_content` sizes the input window to its content (`dont_extend_height`) and reserves menu rows only while a menu is open; the status line keeps counters only, so it fits a 120-column terminal. `test_framed_prompts_stay_compact` reads the rendered screen (frame height and the row under the frame) and failed before the fix.
- **Gap exposed -> change**: pipe-input UI tests prove behavior, not layout. A UI change set now also asserts the rendered rows, and is smoke-run once in a real console (ConPTY) before it is proposed.

## BD-028 — Slash write commands rejected since H3 (/sync, /watch add, /watch remove)
- **Date / discovered by**: 2026-10-02 / owner live session in the terminal UI (`--ui tui`): `/sync` and `/sync run` answered `error: unknown argument(s) ['user_confirmed'] for tool 'sync.run'; allowed: []`.
- **Symptom**: every human-typed slash write command failed before reaching the data layer: `/sync` (run), `/watch add` after `y`, `/watch remove` after `y`. No side effect: each call was rejected at argument validation, so no sync ran, no call budget was spent and the watchlist did not change.
- **Reproduction**: drive `_cmd_sync` and `_cmd_watch` against the real registry with a recording fake data store (TP-022 Driver table); all three paths fail with zero data-layer calls.
- **Classification**: regression - interface drift between a safety fix and its in-repo callers; test-coverage gap.
- **Root cause**: TP-017 PR-2 (H3, PR #51, 2026-09-29) removed the model-fillable `user_confirmed` boolean from every write tool spec, and the registry rejects arguments a spec does not declare. The REPL's three slash handlers still sent `"user_confirmed": True`. The conversational write path (`confirm <token>`) and the CLI subcommands (direct data-store calls) were unaffected. No test executed the slash write paths: the `_cmd_sync` tests covered `status` only, and the TP-021 UI tests cancel `/watch add` before it executes. The defect was live from 2026-09-29 to 2026-10-02.
- **Fix**: the slash calls send exactly their tools' arguments; the gate stays `allow_write=True`, which only these human-typed commands set (after the `[y/N]` yes for `/watch`) (TP-022). The stale `_cmd_watch` docstring is corrected. Not changed: the `register_data_tools` docstring in `agent/registry.py` still describes the removed boolean; agent/registry is a safety-critical path, so that wording waits for the next registry change set.
- **Gap exposed -> change**: a spec change did not reach the spec's in-repo callers, and nothing executed them. `test_slash_tool_calls_match_tool_specs` checks every literal tool call in `agent/repl.py` against its tool's spec, so the next spec change fails the offline suite instead of a live session.

## BD-029 — News dedup/quarantine test started failing on its own, no code changed
- **Date / discovered by**: 2026-10-03 / CI gate (PR #61's "regression" job; unrelated to that PR's own change).
- **Symptom**: `test_ingest_news_sync.py::test_store_filter_dedup_and_quarantine` failed `assert symbol_query["kept_new"] == 2` (got `3`), on a tree whose content was identical to main (which had passed this same test in CI the day before) plus one unrelated file.
- **Reproduction**: offline, with the test's own real helpers: `kept_new=3, dups=1, quarantined=1` instead of the expected `2, 2, 1`; the extra kept row is `"Tencent Holdings buys back shares now"`, which should have deduped against `"Tencent Holdings buys back shares"` via the near-title similarity gate.
- **Classification**: test-fixture time bomb, not a product defect — confirmed by `git stash`-ing the suspect PR's diff and reproducing the identical failure on the unmodified tree.
- **Root cause**: `_article()`'s default `seendate` (`test_ingest_news_sync.py:59`) is the fixed absolute date `20260918T090000Z`; the test never passes `run_news_sync()`'s optional `now:` (`news.py:412`), so it defaults to real wall-clock time. The near-title dedup gate only applies inside a rolling `DUP_WINDOW_DAYS = 14` window (`news.py:63, 272`): `2026-09-18 + 14 days = 2026-10-02`. The test passed through that boundary day and was mathematically certain to start failing on 2026-10-03 — a calendar-dependent fixture, not a regression in `news.py`'s dedup logic, which is correct as written.
- **Fix**: the one `run_news_sync(...)` call in this test now passes an explicit, frozen `now=` comfortably inside the 14-day window, so the test no longer depends on the real calendar date (TP-027).
- **Gap exposed -> change**: a date-sensitive fixture with no frozen clock can pass today and fail tomorrow with zero code changes, and the "regression" CI gate has no way to tell a pre-existing-but-now-failing case apart from a real regression — it blocks every PR equally. No gate change proposed here (out of TP-027's scope); worth a reference-lint-adjacent check later if this class recurs.
