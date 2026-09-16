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
