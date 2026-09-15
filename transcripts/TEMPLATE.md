# Annotated Agent-Session Transcript — TEMPLATE

> Course deliverable D5. Copy this file per student as
> `<student-id>-<student-name>.md`. Fill every bracketed field. The
> transcript must be **raw and complete** (one full session), with the
> student's interventions marked inline and a rationale for each —
> where the team interrupted, redirected, approved, or rejected the
> agent's work. Collective coverage across all students' transcripts
> must demonstrate the full supervised pipeline: requirements
> classification, architecture candidate generation and evaluation,
> plan approval before code, build, verification compliance, and
> architecture revision based on test evidence.

## Session metadata

| Field | Value |
|---|---|
| Student | [name, student ID] |
| Date(s) | [YYYY-MM-DD] |
| Harness / agent | [opencode / pi; model and version] |
| Task phase covered | [requirements / architecture / plan approval / build / verification / architecture revision] |
| Artifacts produced | [paths] |

## Annotated transcript

Paste the raw session (verbatim). Mark every human intervention
immediately after the turn it applies to, using this block format:

```
> **[INTERVENTION #n — approve | redirect | reject | clarify]** by [name]
> What was said/done: [...]
> Rationale: [why the team intervened here — what would have gone wrong without it]
```

Interventions with no rationale do not count.

## Session reflection (by the student, 5–10 sentences)

[What the agent did well; where it went wrong; what the intervention
changed; which governance artifact (registry row, ADR, invariant,
review memo) captured the outcome.]
