# Report — Stock Insider (D6)

Process report for the CS5351 agentic software engineering project. It covers how one person built, verified and maintained an AI-enabled application with AI coding agents under auditable supervision, how that process changed as evidence came in, and what the human supervision caught that the agents did not. Every number in this report can be traced to a record in the repository; the main sources are named where they are used.

## 1. Team and Contributions

The team has one member, who acted as product owner, architect, reviewer, release manager and the only human approver. The relative-contribution weight is therefore 1.0 by construction.

| Member | Student ID | Sprint 1 | Sprint 2 | Sprint 3 | Sprint 4 | Sprint 5 | Total | Relative |
|---|---|---|---|---|---|---|---|---|
| [Name] | [Student ID] | 10 | 5 | 20 | 5 | 7 | 47 | 1.0 |

Contribution measure: approved and implemented change sets, one per test plan (`docs/test-plans/TP-NNN.md`). Each change set is one unit of supervised work. The owner briefed it, approved the plan before any code existed, reviewed the result and merged it. Man-hours were not logged consistently enough to use. The sprints are the five working periods visible in the commit history:

| Sprint | Dates | Theme | Test plans | Commits on main | Bug-diary entries |
|---|---|---|---|---|---|
| 1 | 2026-09-15 to 09-18 | Requirements, architecture, governance, agent foundations, data store | TP-001..TP-009 (10) | 24 | BD-001..BD-011 (11) |
| 2 | 2026-09-21 to 09-27 | Ingestion (fundamentals, news), retrieval, analysis loop | TP-010..TP-014 (5) | 21 | BD-012..BD-018 (7) |
| 3 | 2026-09-29 to 10-05 | Five external review rounds, INV-001 v2, terminal UI, debt remediation | TP-015..TP-034 (20) | 32 | BD-019..BD-029 (11) |
| 4 | 2026-10-26 to 10-27 | News D1 v2, declared result fields, egress on redirect | TP-035..TP-039 (5) | 12 | none |
| 5 | 2026-11-03 to 11-04 | End-to-end tests on the real store, fixes, close-out | TP-040..TP-046 (7) | 8 | BD-030..BD-035 (6) |

Between 2026-10-05 and 2026-10-26 no work happened, which is why Sprint 4 is short.

## 2. Project Overview

Stock Insider is a single-user, local, English-language command-line analyst for Hong Kong and US equities. It ingests daily end-of-day market data, fundamentals where the vendor plan allows, and English news into a local SQLite store with a sqlite-vec index. All market arithmetic is done in deterministic code. An LLM agent answers questions in a REPL, but only through registered tools, and every answer is checked against the values those tools returned in the same session. Sessions are append-only and can be replayed. The product analyzes; it never trades.

Two features make it a meaningful course project rather than a chat wrapper.

- **The AI component is genuine.** The analysis loop is an LLM with tool calling, layered context assembly, compaction, and a news retrieval pipeline built on embeddings.
- **The safety boundary is deterministic.** Four zero-tolerance invariants govern what the AI may say:
  - **INV-001**: every number is verified against the session's tool results or visibly marked `[?]`;
  - **INV-002**: no causal certainty or price predictions;
  - **INV-003**: failures are explicit, never filled with stale or made-up values;
  - **INV-004**: watchlist writes need verified symbol resolution and the user's confirmation.

  The guardrail that enforces them is ordinary code with its own test batteries. It does not depend on the model behaving well.

Final state, at the close of Sprint 5:

| Measure | Value |
|---|---|
| Requirements in the registry | 49 (registry v0.6.3; 47 at baseline) |
| Architecture decision records | 8, carrying 33 dated amendments |
| Test plans approved and implemented | 47 (TP-001..TP-046, with TP-007 split a/b) |
| Merged pull requests | 92, including this close-out |
| Source / test code | about 15,400 / 15,700 lines of Python |
| Offline tests | 839 passing, 2 strict expected failures (recorded unmet targets) |
| Bug-diary entries | 35 |
| AI-use-log entries | 100 |
| Review-memo entries | numbered up to RM-80 |
| Evaluation logbook entries | E-001 to E-015 |

The README covers architecture and usage. This report is about the process.

## 3. Software Engineering Process

### 3.1 Process shape

The project followed the course's governance-first order, then turned into an iterative build-and-verify loop.

1. **Requirements (Sprint 1, day 1).** Four discussion rounds with a pi coding agent turned a feature description into a requirements baseline (AILOG-0001). The agent proposed requirement categories, candidate invariants, MoSCoW priorities and cross-cutting concerns such as exchange calendars, multilingual embeddings and an English-only policy. The owner made every decision: markets, retention, scope exclusions, and which invariants to adopt. The baseline went through v0.1, v0.2 and v0.3 before any file was written. v0.3 was a structural change made on the owner's review (section 6).
2. **Architecture (Sprint 1, day 1).**
   - The agent generated candidate architectures, which were scored in `docs/architecture/evaluation-table.md`: a self-built agent loop against LangGraph, pydantic-ai and smolagents; vendors; storage.
   - The owner confirmed six decisions (AILOG-0004), and they became ADR-001 to ADR-003.
   - Rejected options went to `option-ledger.md` with their reopen conditions, and untested assumptions to `risk-list.md`.
3. **Coding governance (Sprint 1, day 1).** This step produced `AGENTS.md`, the permission model, structural constraints, the tool manifest, and an executable permission gate for the pi harness (`.pi/extensions/governance-gate.ts`).
4. **Verification governance (Sprint 1, day 1).**
   - The CI pipeline got its six blocking gates and the independent check scripts in `tools/checks/`.
   - The living records were started: review memo, debt register, bug diary, AI-use log.
5. **Build (Sprints 1 to 5).** Product code began only after all of the above existed (TP-001, 2026-09-15), and grew one approved test plan at a time.

Sprints 3 and 5 were mostly verification and repair: external review rounds and end-to-end tests on real data found what the offline suite could not. The process spent more effort finding and fixing defects than writing features, and section 4 shows why that was the right allocation.

### 3.2 The change loop

Every change to product code went through the same loop. GOV-006 and the CI test-approval gate enforce it.

1. **Driver.** A requirement, a live finding, an external review finding or a debt item. The agent gathers evidence and states the cause.
2. **Plan.** The agent writes `docs/test-plans/TP-NNN.md`, giving the driver, the scope, the tests to be written (each feature with at least one negative or adversarial case), any assertions that will have to migrate, and the method. The plan is committed first, as its own commit.
3. **Approval.** The owner approves, changes or rejects the plan. The approval is recorded in the plan's header and later in the AI-use log's `human_decision` field. Safety-critical paths (`agent/guardrail*`, `agent/registry*`, `shared/`) and `prompts/` also need an ADR amendment and a review memo.
4. **Build.** Tests and code are written. Where the change is a rule (most guardrail work), mutation checks follow: each rule is reverted in turn, and some test must fail.
5. **Verify.**
   - The full offline suite runs; any failure of an old test is a regression, and the code is fixed, never the test.
   - ruff and mypy run.
   - The 12 structural and PR gates run on a clean clone.
   - For guardrail changes, the error rate is measured on a labelled battery (section 4.4).
6. **Records.** The change set carries its own AI-use-log entry, bug-diary entry, review memo, ADR amendment and evaluation-logbook note, where each applies. The CI gates check that the AI-use log and review memo are actually in the diff.
7. **Merge.** The owner merges after reading the PR. Branch protection requires every check context to pass.

TP-046, the last change set, is a compact example.

- **Driver.** An end-to-end run found three defects (BD-033 to BD-035). The plan was the first commit.
- **Build.** The code followed with eleven tests. Seven mutants were all killed; one test was rewritten because its first version let a mutant survive.
- **Verify.** The post-check change was measured by re-checking 27 live marks, which fell to 12. The PR shipped with ADR-008 Amendment 5, RM-80 and AILOG-0099.
- **Re-test before handover.** A fresh copy of the real store was used again before the PR went to the owner.

### 3.3 Tooling and supervision

**Agents.** Sprints 1 and 2 used the pi coding agent (AILOG-0001 to AILOG-0062). From the end of September, Claude Code was used. The governance was designed to be independent of the harness:
- `AGENTS.md` is read by both harnesses;
- permissions are encoded for opencode (`.opencode/permissions.jsonc`) and enforced for pi by an extension that blocks writes to denied paths;
- `docs/code-governance/pi-adaptation.md` maps one to the other.

The shared backstops are branch protection, review memos and CI, and they do not depend on which agent wrote the code.

**Separation of roles inside one person.** With one human, "reviewer" and "author" could easily collapse into one. Three devices kept them apart.
- **Approval comes before code, not after.** The test-approval gate fails any implementation PR that does not reference a plan marked approved, and the plan must be committed first.
- **Evaluation data has a separate author.** From TP-018 onward, the held-out batteries used to measure guardrail and retrieval changes were written by a separately briefed sub-agent before the rule changed (E-007a, E-010, E-012, E-013, E-014, E-015). The building agent never saw the labels while tuning. Once a battery has been looked at, it is recorded as a development set and only used for regression.
- **External review rounds.** Five times in Sprint 3, the owner commissioned a review from outside the build session: a third-party review and audits two to five. These found classes of defect the building agent had not reported (section 6).

**Branch protection.** A single owner cannot approve their own pull request on GitHub, so the "required approving review" rule deadlocked every merge. Three options were put to the owner, who chose option C (AILOG-0015). The approving-review rule was removed and the owner committed to reviewing every PR as a recorded discipline. The six required status checks, linear history and admin enforcement stayed.

**Session continuity.** Agent sessions do not share memory, and the work ran across dozens of them. Three things carried state:
- the repository records (plans, AI-use log, bug diary);
- a short project memory that the agent kept up to date (open PRs, rebase points, local traps);
- the harness transcripts.

Two traps in the memory each cost a failed step at least twice before they were written down:
- an ignored `proposals/` directory makes the language gate fail in the working copy, so gates are run on a clean clone;
- shell heredocs corrupt backslashes, so long scripts are written to files.

### 3.4 How the process was optimized

The process changed in response to evidence. Each change below has a trigger and a record.

| When | Trigger | Change | Record |
|---|---|---|---|
| Sprint 1 | `AGENTS.md` mixed rules for the coding agent with rules for the product's AI | `AGENTS.md` split into §2a (development rules) and §2b (product invariants as constraints on generated code) | BD-005, AILOG-0009 |
| Sprint 1 | Merge deadlock under single ownership | Approving review became a recorded discipline; required checks unchanged | AILOG-0015 |
| Sprint 1 | Owner's first live conversation failed (HTTP 400, nonexistent default model) | Every milestone ends with an owner live-use round, not only offline tests | BD-008, AILOG-0023 |
| Sprint 2 | Live answers were withheld for display rounding and percent conversion (false positives) | Guardrail changes get an evaluation-logbook entry with measured precision and recall | BD-012, BD-015, E-003, E-004 |
| Sprint 3 | A third-party review found tautological `or True` assertions | A tautology gate was added to CI | TP-016, AILOG-0054 |
| Sprint 3 | The third audit found two PRs claiming "Review-Memo: appended" with no memo in the diff | The test-plan gate checks that a memo entry is actually in the diff for safety paths | RM-51, RM-52, TP-018 |
| Sprint 3 | Battery authors and rule authors were the same agent | Held-out batteries are written by a separately briefed sub-agent before the rule changes | E-007a onward |
| Sprint 3 | Dangling TP and ADR references in docs | A reference lint gate was added | DE-06, TP-026 |
| Sprint 3 | INV-002 recall stalled at 47% against an 80% target | The work stopped, with the residual accepted and a fixed reliability notice shown after every answer | DE-09, TP-034, AILOG-0081 |
| Sprint 5 | Offline fixtures seeded state the product never produced (BD-030 to BD-032) | End-to-end tests run on a sqlite copy of the real store before work is called done | TP-040, TP-045, TP-046 |
| Sprint 5 | Squash merges plus auto-delete closed a stacked PR (#86) | Each stacked PR is retargeted to main before its predecessor merges | AILOG-0094..0098, project memory |
| Sprint 5 | The agent stopped at "PRs are open" | The owner set a stop-hook goal so that "done" became a repository condition | Transcript 2026-11-03 |

The most important change came in Sprint 5. Until then, "all offline tests pass" was treated as strong evidence. The 2026-11-03 smoke test showed 786 green tests alongside four product defects. The tests had seeded the database rows, session index fields and symbol names that the product was supposed to produce, so they tested the readers and not the writers. After that, every change set in Sprint 5 ended with a run on a copy of the real store, and each run found something:
- a digest bug on real timestamps;
- 21 false `[?]` marks;
- the embed failure;
- a wrong symbol name;
- a comparison-table false flag that made the model retract correct numbers.

### 3.5 Architecture revised by test evidence

The architecture started with three ADRs written on day one: runtime and context engineering (ADR-001), data vendor and news ingestion (ADR-002), storage and vector store (ADR-003). Five more were added during the build, each when a module crossed a boundary that needed a recorded decision:
- the shared foundation of cross-module types, egress and language policy (ADR-004);
- the tool registry as the only channel from the agent to the data (ADR-005);
- the runtime guardrail (ADR-006);
- the opt-in terminal UI (ADR-007);
- numeric verification v2 (ADR-008).

What changed most was not the set of decisions but their detail, and almost every change came from a test result. The 33 amendments fall into three kinds:

| Kind | Examples | What triggered them |
|---|---|---|
| A live false positive narrowed a rule | ADR-006 Am1 to Am4 (display rounding, percent display, list markers, ISO dates); ADR-006 Am9 (partial dates); ADR-008 Am3 to Am5 | an owner live session or a real-store test produced a correct answer that the guardrail blocked or marked |
| An adversarial finding closed a gap | ADR-004 Am2 to Am4 (egress for model hosts, loopback as an address); ADR-005 Am3 (confirmation tokens the model cannot relay); ADR-006 Am5 to Am8 | external review rounds two to five |
| A measurement settled a direction | ADR-006 Am11 and Am12 (INV-002 scope, then accepting the measured recall); ADR-008 Am1 and Am2 (typed claims measured on E-010 and E-013); ADR-002 Am2 (news D1 v2 after E-011 and E-012) | an evaluation-logbook entry |

The largest revision was ADR-008. It replaced ADR-006's fallback for INV-001, which withheld an answer, with verify-and-flag, after live evidence showed the old rule was strict on form and loose on meaning. ADR-006 Am10 records the hand-over, so a reader of ADR-006 is sent to its successor instead of finding stale text. Section 4.6 follows that thread in detail.

Two parts of the architecture did not change at all, and that is evidence too.
- **The dependency directions** (shared depends on nothing; data depends only on shared; the agent reaches data only through the registry) were enforced by an import-boundary gate from the first PR and never needed an exception.
- **The decision to build the agent loop by hand instead of adopting a framework** (ADR-001, scored in the evaluation table) was never reopened. Every guardrail revision above needed a hook at an exact point in the loop: before display, after a tool result, at compaction. A self-built loop made each of those a local change.

### 3.6 Verification in three tiers

The course asks for structural, regression and behavioral verification. In practice each tier caught a different kind of problem.

- **Structural tier: 12 scripts in `tools/checks/`, run on every commit or PR.** They check:
  - the registry against its JSON schema;
  - trace coverage, so every requirement appears in the trace matrix;
  - reference lint;
  - the language policy;
  - tautological assertions;
  - the static arithmetic gate (no market-data arithmetic outside `data/compute`);
  - docstring traceability;
  - import boundaries;
  - a secret scan;
  - the AI-use-log gate, a parity gate and the test-plan gate.

  ruff and mypy run in a separate quality job. The tier is cheap and fast, and it caught mainly bookkeeping slips: a YAML entry that swallowed its neighbours (BD-001), a combined trace row (BD-002), a dangling reference (BD-004), a log that stopped being valid YAML (BD-025). It also produced its own false positives, which had to be handled without weakening the gate. TP-045 hit the static arithmetic gate, which taints any variable assigned a market-field string, so a pattern built by joining strings with `+` was read as arithmetic. The fix took the labels from a tuple constant instead of weakening the gate (RM-79).
- **Regression tier: the full offline suite on every PR.** By the close it held 839 tests. The rule that an old test failing is a regression was applied strictly. When a change legitimately moved a pinned value, the plan named it as a migrated assertion and the owner approved it. TP-042 and TP-045 each listed every battery item whose expected result moved. Strict expected failures keep two unmet targets visible: INV-002's 80% recall and QA-002's 0.8 relevance.
- **Behavioral tier: measured quality on labelled batteries and live answers.** This tier decided real questions, such as whether a guardrail change was worth merging, whether to accept a residual, and whether a prompt change could reach production. The CI `eval` job replays a fixed evaluation set on prompt or model changes and blocks if a threshold fails. The batteries (E-006 to E-015) measured the guardrail. Recounting `[?]` marks on stored live answers measured real-use behavior, and these are reported separately from battery numbers.

Mutation checks sit between the regression and behavioral tiers. For rule-level changes from TP-039 on, each new rule was reverted in turn to confirm that some test fails. Mutants survived several times (TP-039, TP-045, TP-046). Each time the cause was a test that did not exercise the rule it named, and a test was added or rewritten.

## 4. Process-Quality Evidence

### 4.1 Requirement volatility

The registry is append-only by rule: a new requirement adds a row, and changing a row counts as a requirement change, which needs an ADR, a version bump and a regression run. Its version history (`docs/req/requirements.yaml`, `meta`) records every change.

| Version | Date | Kind | Content |
|---|---|---|---|
| 0.1 -> 0.3 | 2026-09-15 | Baseline revision, before any code | Run, Turn and Resume unified into one Session model; about a dozen rows rewritten (AILOG-0003) |
| 0.4 | 2026-09-29 | Row-text correction | Eleven `regression_scope` fields pointed at the wrong suites; no acceptance criterion changed |
| 0.5 | 2026-10-01 | Append | FR-026, opt-in terminal UI (ADR-007) |
| 0.6 | 2026-10-02 | **Requirement change** | INV-001, FR-008, QA-004: from withholding an answer with an unverified number to verifying and flagging it |
| 0.6.1 | 2026-10-02 | Scope field | INV-001 regression scope gains the typed-claim suite |
| 0.6.2 | 2026-10-26 | Append | FR-027, curated topical news bucket |
| 0.6.3 | 2026-10-26 | Scope field | FR-027 regression scope points at the suite that now exists |

During seven weeks of building, the registry had two appended requirements and one real change to an existing requirement. The other entries corrected bookkeeping. Low volatility after the baseline is what the governance-first order was meant to buy, and it did. The one real change came from live evidence (section 4.3) and followed the full procedure: owner decision, ADR-008, registry 0.6, migrated assertions listed one by one in AILOG-0070.

Scope stayed fixed. The `scope_must_not_do` list, which includes never trading and never fabricating, was never loosened. Two Could-priority requirements, FR-024 (Chinese news) and FR-025 (quant models), were deferred on purpose. FR-009 (event scoring) is the one Must-list capability that remains unimplemented. The weekly digest reports its section as unavailable, as INV-003 requires, instead of hiding it.

### 4.2 Defect trends

The bug diary has 35 entries; BD-006 has a later correction entry. Grouped by sprint and by who found them:

| Found by | S1 | S2 | S3 | S4 | S5 | Total |
|---|---|---|---|---|---|---|
| Owner, in review or first live use | 6 | 2 | 2 | 0 | 0 | 10 |
| Agent, in an owner-instructed live round or real-store test | 0 | 5 | 1 | 0 | 6 | 12 |
| External review commissioned by the owner | 0 | 0 | 5 | 0 | 0 | 5 |
| CI gate or validation script | 4 | 0 | 1 | 0 | 0 | 5 |
| Agent self-check | 1 | 0 | 2 | 0 | 0 | 3 |
| **Total** | 11 | 7 | 11 | 0 | 6 | 35 |

The nature of the defects shifted from sprint to sprint.

- **Sprint 1: wrong facts about the outside world.**
  - The default model name did not exist at the provider (BD-008).
  - The resolver ignored the key in the env file (BD-009).
  - The egress whitelist named a nonexistent vendor host (BD-010).
  - Benchmark indices used the suffix `.IND` instead of `.INDX` (BD-011).

  The agent had written these from plausible assumptions, and offline tests with mocked vendors passed. The owner's first live use exposed each one within minutes.
- **Sprint 2: guardrail false positives on real answers.** Correct numbers were blocked because the model rounded them for display, converted fractions to percents, or numbered a list (BD-012, BD-015, BD-016, BD-018). Each was found in the first live run of a new feature.
- **Sprint 3: bypasses and dishonest reporting.** External reviews found that the post-check could be bypassed by numbers glued to letters (BD-020), that the egress loopback exception matched a hostname prefix (BD-021), and that a history window counted events instead of messages (BD-023). Empty market answers were reported as fresh (BD-024). These are security and integrity defects, and the building agent had not reported any of them.
- **Sprint 4: no new diary entries.** That sprint was planned work on known debt, and it measured its own error rates (E-011 to E-014).
- **Sprint 5: integration defects on real data.** Rows written by an old build were demoted by a later migration (BD-030). A Must requirement was never written to its field (BD-031). Vectors could not be updated once they existed (BD-033). A comparison table was read against the wrong column (BD-035). Every one passed the offline suite.

Two conclusions shaped the process.
1. 27 of the 35 defects were found by running the real product or by a reviewer outside the build session, and only 8 by gates or self-checks. Offline tests are necessary, but they verify the designer's model of the world, not the world.
2. Severity fell over time while the detection effort rose. The Sprint 3 defects could have caused real harm (unverified numbers shown as verified, outbound traffic to arbitrary hosts). The Sprint 5 defects were mostly about usability and accuracy.

### 4.3 Ambiguity resolution

Several ambiguities were resolved explicitly, and each resolution is on record.

- **Run versus Session (Sprint 1).** The glossary defined an "agent run", FR-013 described a REPL, and FR-023 described one-shot "ask" semantics. These are three incompatible models of a conversation. The owner noticed the conflict in review and ruled that there is one Session model: follow-ups and resume are part of it, artifacts are written per turn and never overwritten, and the analysis profile is locked per session (AILOG-0003, registry v0.3). The agent had produced all three definitions without noticing the conflict.
- **Withhold or flag (Sprint 3).** INV-001 originally said an answer with an unverifiable number is withheld. On 2026-10-02 two live answers about BYD were withheld whole, one for a news timestamp written to the millisecond, one for "about 37%" stated for a volatility of 0.3711553760998695. A probe found the check strict about form and loose about meaning: correct roundings were blocked while misattributed numbers passed. The owner ruled that rounding is not data modification, and that the answer should point at the suspect numbers instead of disappearing (AILOG-0070). The fix was not a patch but ADR-008, a three-phase redesign into typed claim verification. It ran from TP-023 to TP-025 and was then refined by four amendments, each driven by live evidence.
- **What "verified" means for a name.** Symbols added through the HK direct-verification path (BD-017) carry a placeholder name. Two later defects show the same unsettled question, whether a placeholder is a verified name: BD-032 (the placeholder treated as an official name) and BD-034 (the placeholder applied to US symbols that the vendor's search does index). Each was settled by narrowing where the placeholder can appear, not by changing INV-004.
- **When to stop.** The INV-002 epistemic filter's recall on a sealed battery stayed at 47% after a full fix round, against an 80% target, with no false flags on the control set. Pattern-based detection of causal language has diminishing returns. The owner stopped the work, kept the unmet target as a strict expected failure so it cannot silently pass, and added a fixed sentence after every answer: "Agent is a probability machine, which may make mistakes" (DE-09, TP-034). Retrieval relevance (QA-002, 0.736 against 0.8) was handled the same way (AILOG-0084).

### 4.4 Evaluation evidence

The guardrail and retrieval were measured, not just tested. The evaluation logbook has 15 entries (more counting sub-entries). The ones that drove decisions:

| Entry | What was measured | Result | Decision |
|---|---|---|---|
| E-006, E-007 | INV-002 filter on a labelled suite and the audit battery | precision and recall recorded per class | the battery becomes a development set; new batteries are author-separated |
| E-008 | INV-002 on the fifth-audit batteries | recall short of target | DE-09 opened |
| E-010 | INV-001 typed claims, held-out set by a separate author | precision 0.918, recall 0.850 on the first run of the frozen engine | ADR-008 phase 2 adopted |
| E-012 | Retrieval variants on held-out queries | best variant 0.736 relevance@5 | residual accepted (D10a) |
| E-013 | Phase-3 typed claims, independent | precision 0.817, recall 0.906 | follow-up plan TP-039 |
| E-014 | Growth phrasing and the name/cue collision | precision 0.710 -> 0.817, recall 1.00 | merged (TP-039) |
| E-015 | False flags seen in live use, independent battery of 223 claims | precision 0.630 -> 0.977, recall 0.780 -> 0.860 on the independent run | merged (TP-042); the fix after measurement is disclosed with both numbers |

Two discipline rules stand out.
- **A battery is used once as an independent measure.** After that it is a development set and runs only as regression. TP-045 and TP-046 changed the post-check without an independent battery, because every existing battery had already been looked at, and both say so in their plans, PRs and ADR amendments. Whether to commission a fresh battery (E-016) is left as an open owner decision, not hidden.
- **Measurements on real use are recorded separately from battery results.** The logbook notes for 2026-11-03 and 2026-11-04 count the `[?]` marks on stored live answers before and after each change: 21 to 3, then 27 to 12. These are not precision figures and are not presented as such.

### 4.5 Technical debt

The debt register tracks 18 items across the course's AI-era categories. Examples:
- **evaluation debt**: performance thresholds deferred, DE-01; zero empirical evidence at the start, DE-02;
- **guardrail debt**: heuristic typing, DE-15; names missing from the ledger, DE-16; INV-002 recall, DE-09;
- **hidden dependencies**: a duplicated dotenv reader, DE-07;
- **governance gaps**: Bash command governance is heuristic, DE-03; pi role separation is behavioral, DE-04.

Most items were repaid by a test plan in Sprint 3 or 4: DE-06, DE-08, DE-11, DE-14 and DE-18 among them. The ones that remain open are recorded as accepted residuals with a reason and a reopen trigger, not left vague. Debt items were opened by evidence: review findings, unmet measurements, live failures. None was opened speculatively.

### 4.6 Case study: INV-001 from first live use to close-out

INV-001 is the invariant that most directly constrains the AI: every number shown to the user must match a value a tool returned in the same session, or be visibly marked. Its history touches every part of the process, so it is worth following in one place.

**Version 1 (Sprint 1 to Sprint 3, ADR-006).** The post-check was built to the requirement as written. It extracted every number from an answer and compared it with a pool of numbers from the session's tool results. An unmatched number caused the whole answer to be withheld. Offline tests passed. The first live answers did not:
- a price rounded to two decimals was blocked (BD-012);
- a fraction shown as a percent was blocked (BD-015);
- a numbered list was read as numeric claims (BD-016);
- an ISO date split into three numbers (BD-018).

Each was fixed with a narrow allowance and an ADR-006 amendment. Later rounds found the opposite problem, numbers that should have been checked but escaped. A user-simulation round found a pool keyed by tool name, so a later call silently replaced an earlier one (BD-019). The fifth external review found numbers glued to letters (BD-020). By the end of Sprint 3, ADR-006 had been amended nine times and the check was still unreliable in both directions.

**The redesign (2026-10-02).** Two live answers about BYD were withheld for one number each. The owner asked for a probe instead of another patch. The probe showed the check was mostly a string match: it ignored which company and which field a number belonged to, so a correctly rounded volatility failed while another company's price could pass. The owner made three decisions:
- claims are typed by subject and field;
- rounding to any written precision is allowed;
- an unverifiable number is flagged, not withheld.

These became registry v0.6, ADR-008, and three phases: TP-023 (flag instead of withhold), TP-024 (the typed claim engine) and TP-025 (tools declare the meaning of their result fields, and names travel with results).

**Measurement discipline.** Each phase was measured on a battery its rules had not seen, written by a separate sub-agent before the rules changed:
- E-010: precision 0.918 and recall 0.850 on the first run of the frozen engine;
- E-013 after phase 3: 0.817 and 0.906;
- E-014 after the TP-039 follow-up: precision from 0.710 to 0.817 with recall 1.00.

Each result named its residual classes, and those became the next plan's scope or an accepted debt item (DE-15, DE-16).

**Live use again (Sprint 5).** The 2026-11-03 smoke test showed precision on real answers was lower than any battery suggested. Twelve correct numbers in one report were marked, because the model wrote numbers in shapes no battery contained: "High 74.9 · Low 73.3", section numbers, headline figures, sentiment fields. A new independent battery, E-015 with 223 claims built from those shapes, measured precision 0.630 before TP-042 and 0.977 after. Re-checking the stored live answers found further shapes:
- TP-045 took 21 marks to 3, two of them correct flags;
- TP-046 took 27 marks to 12, including a comparison table whose column was read against the wrong company.

**What the thread shows.** The specification, not the code, was the first thing wrong, and only use revealed it. Patching produced a rule nobody could reason about; a redesign with measured phases produced one that could be improved predictably. And every battery, however carefully built, lagged behind the shapes real answers take. That is why Sprint 5 ended each change with a real-store test, and why E-016 is recorded as an open decision instead of claiming that the last two amendments are measured.

## 5. Keeping Artifacts Co-Evolving

Every change could touch several artifacts at once: a requirement row, the trace matrix, an ADR, the invariant register, `AGENTS.md`, the permission model, tests, the review memo, the AI-use log. The process kept them consistent in four ways.

1. **One change set carries every artifact it affects.** GOV-006 (approved test plans) is the clearest case. Adding it meant changing the registry, the trace matrix, `AGENTS.md` §7, the permission model, the glossary and CI together, and they shipped together. TP-046 did the same at a smaller scale: one PR held the code, tests, plan, ADR amendment, logbook note, three bug-diary entries, a review memo and the AI-use-log entry.
2. **Gates check the links, not just the files.**
   - The AI-use-log gate fails a PR that changes `src/` or `prompts/` without a log entry.
   - The test-plan gate fails one that changes code without an approved plan covering the files, or that claims a review memo without one in the diff.
   - The docstring gate requires every module and public function to name the requirement and ADR it implements.
   - The trace-coverage gate requires every registry entry to appear in the trace matrix.
   - The reference lint fails on a citation of a TP, ADR or debt item that does not exist.

   These links are what let a reader go from a requirement to its code, its tests and its decisions without trusting the prose.
3. **Amend, don't rewrite.** ADRs carry dated amendments (33 across eight ADRs) instead of silent edits. ADR-006, the guardrail, has twelve, so its history can be read in order. Old test assertions are never edited to make code pass. When a change legitimately alters a pinned value (a version string, a tool list, a battery's false-flag set), the plan lists each "migrated assertion" with its reason, and the owner approves them. Expected failures are strict: if an unmet target is ever met, the test fails, and someone has to update the record.
4. **Context freshness for the agent.** `AGENTS.md` routes and never duplicates: a sentence that appears both there and in another artifact counts as a review defect. Agents therefore read the source artifact, not a stale copy. The project memory records which facts went stale and why, for example the registry count in the README.

Co-evolution did fail in a few places, and those failures are instructive.
- The identity prompt gained rules in two bug fixes without its version field being bumped. A third-party review caught it (AILOG-0054).
- The README's "implemented features" paragraph fell behind the code, until the close-out update.
- The offline fixtures drifted from the shape the product actually writes (BD-030 to BD-032).

In each case the cause was an artifact that no gate linked to the change.

## 6. What Human Oversight Caught That the Agent Did Not

The agents were capable and fast. Most of what they missed came from three sources: they trusted their own assumptions about the outside world, they treated green tests as proof, and they followed their own plan even when it was inconsistent. The record has these cases:

1. **Three incompatible conversation models in the requirements (AILOG-0003).** The agent wrote the Run definition, the REPL behavior and the one-shot "ask" semantics in separate rounds and never noticed they conflicted. The owner did, and the Session model that came out of it has stayed stable since.
2. **Role confusion in `AGENTS.md` (BD-005, AILOG-0009).** The agent wrote the product's runtime invariants as if they were rules for itself. A coding agent reading "never emit unverified numbers" could reasonably refuse to write a test fixture containing numbers. The owner caught it in review and asked for an audit of the whole file for the same class of mistake.
3. **Assumed facts about vendors (BD-008 to BD-011).** Model name, env-file loading, API host, index suffix: each was plausible, untested against reality, and wrong. The owner found all four within the first two days of live use. The agent had passing tests for all of them, because the tests mocked the vendor.
4. **Forged review records (RM-51, RM-52).** Two PRs claimed "Review-Memo: appended", but no memo was in the diff. The building agent did not notice. A third audit commissioned by the owner did. The fix was a gate, not a reminder: the test-plan gate now checks that a memo entry is actually added for safety paths.
5. **Guardrail bypasses (BD-020, BD-021).** Numbers glued to letters escaped the post-check, and the loopback exception for egress matched on a hostname prefix instead of the exact host. The building agent had tested the guardrail on the cases it designed for. The external reviewer tested it on cases built to break it.
6. **A requirement that was right on paper and wrong in use (INV-001, 2026-10-02).** The agent had implemented withholding exactly as specified, and it worked as specified. The owner looked at a real answer that had disappeared because of a correctly rounded number and decided the specification was wrong. No agent was positioned to make that judgment. It required knowing what the product is for.
7. **Knowing when to stop (DE-09, QA-002).** The agent would have kept tuning patterns. The owner weighed 47% recall against the cost of further pattern work and the risk of overfitting to a consumed battery, and chose an honest notice instead.
8. **Testing the product, not the tests (2026-11-03).** The agent's suggested next step was to start the course report. The owner asked instead for an end-to-end test of every CLI feature, and scoped the agent's access to the real store for that test only. Four defects followed, including a Must requirement that had never worked in practice. The 2026-11-04 test, also owner-requested, found the cause of an embed count mismatch that the agent had noticed the day before and filed as a follow-up without diagnosing.
9. **Keeping the merge decision human.** Three times on 2026-11-03 the owner's stop hook pushed the agent toward "done" while PRs were unmerged. It did not merge them itself, because AGENTS.md reserves safety-path and prompt changes for the owner. Instead it verified more and asked. The owner's merge approvals in the transcripts come after green CI and verification on a copy of the real store, and they cover the specific migrated assertions and label rulings, not just "looks good".

The agents also caught things the owner did not. For balance, examples:
- the fixture-seeding diagnosis behind BD-030 to BD-032;
- the digest's failure on real GDELT timestamps, found during the agent's own verification;
- many mutation-check failures, each showing that a new test did not test what it claimed.

The division of labor that emerged is the one the course describes: the agent explores, implements and measures, and the human decides what correct means and when evidence is enough.

## 7. Self-Reflection

### [Name — Student ID]

*Draft written from the project record, for the owner to revise in their own words.*

I started this project expecting the hard part to be the code. It turned out to be deciding what to believe. By the end of the first week the agents could produce a module, its tests and its documentation faster than I could read them, and everything passed. What I learned over the next five weeks is that "everything passed" mostly told me the agent agreed with itself.

The moments I am proudest of are the ones where I did not accept a green result. On the first day, the requirements read well, but the glossary, the REPL behavior and the "ask" command described three different products. On the first live run, the default model name did not exist. In October, a guardrail I had specified exactly as written was throwing away correct answers, and I had to admit the specification was wrong, not the code. In November, after more than 780 offline tests passed, I asked for a plain end-to-end test, and four defects appeared in an afternoon. None of those catches needed deep expertise. They needed me to use the product as a user would, and to read what the agent wrote as a reviewer, not as its co-author.

Working alone made the governance more important, not less. There was no teammate to notice that I had approved my own shortcut. The rules I came to rely on were the ones that made approval happen before work instead of after:
- test plans committed before code;
- evaluation batteries written by a separate agent before the rule changed;
- gates that checked a review memo was really in the diff.

The rules that were only written down, such as "the owner reviews every PR", depended on my discipline, and that is where the forged review-memo claims slipped through until an outside audit found them.

The thing I would change is when I started end-to-end testing. I treated it as a final check when it should have been part of every change. The most expensive defects in the project, a migration that silently disabled a whole verification layer and a requirement that never worked, were sitting in plain view of anyone who ran the program on real data. I also learned to stop: a 47% recall that would not move, and a retrieval score just under target, were better handled by an honest notice and a recorded residual than by another round of tuning to a test set I had already seen.

## 8. Limitations and Residual Risks

These are open at the close of the project, each recorded where noted.

- **INV-001 claim typing is heuristic (DE-15).** It has improved through five ADR-008 amendments, but no independent battery measures the last two (TP-045, TP-046). E-016 is an open owner decision. Known residual classes are a subject written after its number, number words used as adjectives, and some date shorthands.
- **INV-002 recall is 47% on its sealed battery (DE-09).** It is accepted, with a visible reliability notice.
- **QA-002 retrieval relevance is 0.736 against 0.8 (DE-17).** It is accepted, to be re-measured if article bodies are embedded.
- **FR-009 event scoring is not implemented.** The digest reports it as unavailable.
- **Vendor-side issues.** HK listings are missing from vendor search, so symbol verification for HK uses a direct path (BD-017). The fundamentals feed is not in the current plan, and GDELT rate limiting recurs. All three are reported explicitly at runtime.
- **The early sessions are lost.** Transcripts of the Sprint 1 sessions, where requirements were classified and architecture candidates generated, were not kept. That phase is evidenced by the AI-use log (AILOG-0001 to AILOG-0013), the evaluation table, the option ledger and the commit history, not by a transcript.

## 9. Appendix — Where the Evidence Is

| Evidence | Location |
|---|---|
| Every AI-authored change and the human decision behind it | `docs/ai-use-log.yaml` (AILOG-0001..0100) |
| Requirements and their version history | `docs/req/requirements.yaml` (`meta` comments) |
| Architecture decisions and amendments | `docs/architecture/adr/` |
| Candidate comparison, rejected options, risks | `docs/architecture/evaluation-table.md`, `option-ledger.md`, `risk-list.md` |
| Measurements | `docs/architecture/evaluation-logbook.md` |
| Approved plans | `docs/test-plans/TP-001.md` .. `TP-046.md` |
| Defects | `docs/bug-diary.md` |
| Reviews | `docs/review-memo.md` |
| Debt | `docs/debt-register.md` |
| Annotated agent sessions | `transcripts/` |
| Gates | `.github/workflows/ci.yml`, `tools/checks/` |
