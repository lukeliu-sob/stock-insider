# Verification Constraints — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/code-governance/verification-constraints.md` (course deliverable D4) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Registry baseline | `docs/req/requirements.yaml` v0.3.2 |
| Related | `architecture-blueprint.md` §10; `trace-matrix.md`; `.github/workflows/ci.yml` (execution); `tools/checks/` (structural scripts) |

Verification rules the verification agent applies and the QA records the team maintains. Normative: CI encodes these mechanically; a rule without a CI hook is tracked as debt until automated.

## 1. The Ten Rules

| # | Rule | CI hook |
|---|---|---|
| R1 | **Fit-criterion coverage**: every registry entry with `regression_trigger: true` has at least one real test in its `regression_scope`; the trace matrix's ID set equals the registry's ID set exactly (no requirement without a test = unkept promise; no test without a requirement = deletion debt). | `tools/checks/trace_coverage.py` |
| R2 | **Invariants fail when violated**: every invariant carries an adversarial/mutation suite with zero-escape criteria (inject a fabricated number → post-check must reject; elicit a prediction → filter must block). | adversarial suites in `test/offline/` |
| R3 | **Test ↔ requirement mutual reference**: every test carries a requirement/invariant ID (pytest marker `@pytest.mark.req("REQ-SI-FR-006")` or docstring line); IDs must exist in the registry. | `tools/checks/docstring_ids.py` (code side) + review memo (test side) |
| R4 | **Zero regressions**: every PR runs the full prior suites; an old test failing is a regression — fix code, never the test. | CI regression job (D7-5) |
| R5 | **Three tiers, three moments**: structural (every commit, seconds) · regression (every PR) · behavioral (prompt/model changes → evaluation gate; invariant-path changes → adversarial suites). | CI job layout |
| R6 | **Offline/live separation**: offline is the blocking default; live tests never run in the default gate. The **evaluation gate is the one triggered exception** defined by GOV-003/QA-001 — it is a distinct, conditionally-triggered gate, not a violation of this rule. | CI job triggers |
| R7 | **Negative-test duty**: every feature ships at least one adversarial/negative test. | review-memo check item |
| R8 | **Boundary ±1**: threshold rules (QA thresholds, budget envelopes, watchlist cap) carry boundary and boundary±1 cases. | review-memo check item |
| R9 | **Test independence**: offline tests never touch live services; fixtures live in `test/offline/fixtures/`; live tests are separately marked and skippable. | CI regression job scope |
| R10 | **Architectural fitness functions**: import direction, module↔element bijection, docstring traceability, and the language policy are scripted and run on every commit. | `tools/checks/*` |

## 2. Test-Plan Approval Process (GOV-006, blocking gate D7-1)

1. Before implementation begins, the change's tests are written as a **test plan**: `docs/test-plans/TP-NNN.md` from `TEMPLATE.md`, listing target requirement IDs, planned test files, negative tests, and boundary cases.
2. The test plan is committed and **approved** (status flips to `approved` with approver and date) in its own change set — before the implementation PR starts.
3. The implementation PR body must contain `Test-Plan: TP-NNN`. CI (`tools/checks/testplan_gate.py`) blocks PRs touching `src/` or `test/` without a valid, approved reference.
4. Approval preceding implementation is verified from file history by the reviewer (full mechanical ordering automation was considered and rejected as over-engineering for a course team — recorded in GOV-006 tradeoff).

## 3. CI Job Map (`.github/workflows/ci.yml`)

| Job | Blocks on | Contents |
|---|---|---|
| `structural` | every commit | registry schema gate (D7-3) · trace coverage · language gate · docstring IDs · import boundaries · secret scan (D7-2 partial) |
| `quality` | every commit | ruff + mypy (existence-guarded until `pyproject.toml` lands — debt DE-05) |
| `regression` | every PR | `pytest test/offline` + coverage report (report-only, no threshold) (D7-5) |
| `gates` | every PR | AI-use log gate (D7-6) · governance parity gate |
| `approval` | PRs touching `src/` or `test/` | test-plan reference validation (D7-1) |
| `eval` | PRs touching `prompts/` or provider/model routing | evaluation-set replay against QA-001 thresholds (D7-4); runs with repo-secret provider key |

Branch protection requires all jobs green; safety-critical paths additionally require owner review (CODEOWNERS) and a linked ADR in the PR body.

## 4. Guard-Removal Discipline

Until the codebase scaffolding lands, `quality` and `regression` run under existence guards (they pass with a note when `pyproject.toml` / test files are absent). **Every guard is debt (DE-05) and its removal is its own PR** with its own test plan. Guards must never silently become permanent.

## 5. Records

- **Review memos** (`docs/review-memo.md`): one entry per PR; verdict APPROVE / CHANGES REQUIRED / REJECT.
- **Debt register** (`docs/debt-register.md`): AI-era debt categories, seeded and maintained.
- **Bug diary** (`docs/bug-diary.md`): one entry per significant bug, including the invariant/process gap it exposed.
