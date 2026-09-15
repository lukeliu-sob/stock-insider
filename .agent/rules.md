# .agent/rules.md — Project Covenant (HUMAN-ONLY FILE)

> Authored by humans; the coding agent reads it as a constraint. Changes require owner
> approval. Context-freshness rule (§6) is checked at every sprint boundary.

## 1. Abstraction Limits

- No new abstraction layer, framework, or "internal DSL" without an ADR.
- Three strikes rule: a helper is promoted to `shared/` only when a third caller appears; premature generalization is debt.
- The agent loop stays a loop: no plugin architecture unless an ADR opens one.

## 2. Dependency Constraints

- Minimal set; all dependencies pinned; license-compatible.
- No training-grade dependencies (torch-class) — registry FR-025 gate.
- New dependency = stop-and-ask + ADR recording why existing options fail.

## 3. Test Independence

- Every feature carries at least one negative/adversarial test (what must fail, not only what must pass).
- Invariants carry adversarial suites with zero-escape criteria; threshold rules carry boundary ±1 cases.
- Tests never depend on live services in the offline gate; live tests never block.

## 4. Safety-Critical Change Rule

Changes to `agent/guardrail`, `agent/registry`, `shared/` (egress whitelist, schemas), `prompts/`, or CI workflows require: an architecture decision + explicit human approval before merge. No exceptions for "small fixes" — small fixes to guardrails are how guardrails erode.

## 5. Traceability Duty

Every module and public function references the requirement/invariant and ADR it implements (structural-constraints §4). A change that cannot name its requirement is a change without a reason.

## 6. Context Freshness

When the registry changes, all dependent artifacts (AGENTS.md routing, structural constraints, permission matrix, prompts, glossary) are updated **within the same sprint**. Stale paragraphs actively mislead coding agents — they are defects, not inconveniences.
