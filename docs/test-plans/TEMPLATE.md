# Test Plan TP-NNN — <change title>

| Field | Value |
|---|---|
| Plan ID | TP-NNN |
| Status | draft | <!-- draft | approved | superseded -->
| Date | YYYY-MM-DD |
| Author | |
| Approver | (owner; set when status flips to approved) |
| Approval date | (must precede implementation PR start) |
| Target requirements | REQ-SI-XXX-NNN [, ...] |
| Implementation PR | (filled when the PR opens; body must contain "Test-Plan: TP-NNN") |

## Scope

What changes, which modules (must match the requirements' trace-matrix components), and what explicitly does **not** change.

## Planned tests

| Test file | Verifies (REQ-ID) | Kind | Notes |
|---|---|---|---|
| `test/offline/test_xxx.py::test_yyy` | REQ-SI-... | positive | |
| `test/offline/test_xxx.py::test_yyy_neg` | REQ-SI-... | negative/adversarial | what must fail |

## Negative tests (mandatory, R7)

At least one adversarial/negative test per feature: what input or mutation must be rejected, and what the expected failure mode is.

## Boundary cases (R8, for threshold rules)

Boundary and boundary ±1 cases for any threshold touched (QA thresholds, budget envelopes, watchlist cap).

## Fit-criteria mapping

How the planned tests jointly cover each target requirement's `fit_criterion` (point to specific assertions).

## Regression scope

Prior suites that must stay green (from the registry `regression_scope` of touched requirements).
