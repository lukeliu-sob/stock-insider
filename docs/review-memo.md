# Review Memo — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/review-memo.md` (course deliverable D4) |
| Discipline | One entry per pull request, appended below. Entries are never edited after verdict except to add a follow-up note. |

## Verdict rules

- **APPROVE** — all sections check out; merge.
- **CHANGES REQUIRED** — concrete deficiencies listed; re-review after fixes.
- **REJECT** — spec or architecture misalignment that cannot be fixed within the PR (wrong requirement understanding, boundary violation, invariant erosion); the task returns to planning.

Security and efficiency are checked **throughout** every section, not as an afterthought. Permission compliance includes harness parity: if `.opencode/` or `.pi/` governance changed, `pi-adaptation.md` must be in the same change set.

## Entry template

```
## RM-NNN — PR #<number>: <title>

Date / reviewer / author (human or AI-drafted, human-approved):

Spec alignment:
  - Requirements touched (IDs):
  - Test plan referenced (TP-NNN, approved):
  - Fit criteria satisfied (evidence):

Architecture alignment:
  - Modules touched (must equal requirement's trace-matrix components):
  - Dependency direction respected:
  - ADR linked (mandatory for safety-critical paths):

Code quality:
  - Docstring traceability (Implements: lines):
  - Complexity / duplication / naming:

Test quality:
  - Negative/adversarial tests present:
  - Boundary ±1 cases (threshold rules):
  - Full prior suites green (zero regressions):

Operational metadata:
  - Runtime impact (if agent/ touched): token budget, policy paths affected
  - Performance/cost observations:

Security & efficiency (throughout):
  - Injection surface / sanitization:
  - Egress and secrets:
  - Resource efficiency:

Governance:
  - AI-use log updated in change set:
  - Permission matrix compliance (incl. harness parity):

Verdict: APPROVE | CHANGES REQUIRED | REJECT
Conditions / follow-ups:
```

## Entries

*(none yet — the first entry is created with the first implementation PR)*
