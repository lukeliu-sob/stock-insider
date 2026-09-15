# Report — Stock Insider (D6)

> Process report skeleton. Requirements (course D6): all students'
> names and student numbers; relative-contribution table; at most
> 10,000 words excluding diagrams; 15+ pages at 12pt single spacing;
> team software-engineering process and its optimization; per-member
> self-reflection (300–500 words each); process-quality evidence
> (requirement volatility, defect trends, ambiguity resolution); how
> artifacts were kept co-evolving; what human oversight caught that the
> agent did not.

## 1. Team and Contributions

| Member | Student ID | Sprint 1 | Sprint 2 | Sprint 3 | Sprint 4 | Sprint 5 | Total | Relative |
|---|---|---|---|---|---|---|---|---|
| [name] | [id] | | | | | | | |
| [name] | [id] | | | | | | | |

Contribution measure: [pre-agreed man-hours / story points — state the
team's measure explicitly].

## 2. Project Overview

[Purpose, scope, the analysis-only boundary; pointer to README.]

## 3. Software Engineering Process

### 3.1 Process shape

[Governance-first trajectory: requirements registry → architecture →
coding governance → verification governance → implementation sprints;
the AI-proposes / human-decides loop; test-plan-first change flow.]

### 3.2 Tooling and supervision

[opencode + pi parity; the governance gate; review memos; the six
blocking gates; branch protection.]

### 3.3 Process optimization

[What the team changed mid-course and why — e.g., the registry version
history (v0.2.0 → v0.3.2) records real requirement revisions: the
Session-model unification, values-as-seen snapshots, GOV-006 addition.
Use the registry and AI-use log as evidence, not prose claims.]

## 4. Process-Quality Evidence

- **Requirement volatility**: registry version history; entries added
  vs. rewritten per round; how disputes resolved (three-list scope
  negotiation, MoSCoW tradeoffs recorded per entry).
- **Defect trends**: bug-diary entries BD-001..005 (process-phase
  incidents) and implementation-phase entries as they accrue; which
  layer caught each (human review / AI self-check / CI gate).
- **Ambiguity resolution**: examples — the Run/Session terminology
  conflict (BD-005-class), the embedding-endpoint uncertainty, the
  "insider" codename ruling.
- **Artifact co-evolution**: concrete instances — GOV-006 addition
  rippling through trace matrix, AGENTS.md, permission model,
  glossary, CI in one change set.

## 5. What Human Oversight Caught That the Agent Did Not

[Evidence on record: BD-005 / AILOG-0009 (AGENTS.md role confusion —
owner-caught); the v0.2→v0.3 Session-model simplification (owner
caught a three-way inconsistency); rate-limit tier-upgrade ruling;
scope rulings (Won't list). Add implementation-phase examples as they
occur.]

## 6. Self-Reflections

### [Name — Student ID]

[300–500 words per member.]

## 7. Appendix

[Pointers: `docs/ai-use-log.yaml`, `docs/bug-diary.md`,
`docs/debt-register.md`, registry version history, transcripts/.]
