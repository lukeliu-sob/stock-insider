# Structural Constraints — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/code-governance/structural-constraints.md` (course deliverable D3) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Related | `AGENTS.md` §5–6; `architecture-blueprint.md` §5; `permission-model.md` |

Module organization rules the coding agent must satisfy. These are CI-checkable (structural tier, blueprint §10).

## 1. Module ↔ Architectural Element Bijection

Every module in `src/stockinsider/` maps to exactly one architectural element from blueprint §5, and vice versa. Adding a module without an architecture entry is a defect; an architecture element without a module is tracked traceability debt (trace matrix). Current mapping: see blueprint §5 table — it is the single source; this document does not duplicate it.

## 2. Baseline Discipline

1. New work **extends** the existing baseline; it never replaces it.
2. No module rewrites or relocations without an ADR and owner approval.
3. Deleted code paths require a registry retirement entry (deprecation protocol) before removal.

## 3. Dependency Direction Rules

Normative statement (also in AGENTS.md §5, repeated there in compact form for context economy):

```
shared    → nothing internal
data/*    → shared only
agent/registry → data facade + shared     (the only agent→data channel)
agent/*   → shared + agent/registry
cli       → agent facade + data facade
Forbidden: data→agent · agent(non-registry)→data · anything→cli
```

CI enforcement: an import-linter-style check fails any violation, including transitive ones.

## 4. Docstring Traceability Convention

Every module and every public function/class carries:

```
Implements: REQ-SI-FR-006, REQ-SI-QA-003 (ADR-001)
```

Rules:

1. At least one requirement ID; ADR reference when an architecture decision governs the design.
2. IDs must exist in the registry (CI checks docstring IDs against the registry ID set).
3. Invariant enforcement points must name the invariant: e.g., `agent/guardrail` functions reference `REQ-SI-INV-001`.
4. Docstrings are English (GOV-001); IDs are ASCII by construction — the language check includes docstrings.

## 5. Authority Boundaries in Code

- Modules in `data/` and `agent/registry`, `agent/guardrail`, `shared/` are **authoritative**: their decisions are final; no advisory-layer code may override them.
- Modules in `agent/` (other than registry/guardrail) are **advisory-side**: they orchestrate and narrate; they never compute market-data arithmetic (static gate, FR-006) and never touch storage directly.
- The runtime LLM has no code-level representation beyond provider calls in `agent/providers`; it executes nothing else.

## 6. Schema and Provenance Home

All cross-module data shapes (tool input/output schemas, provenance enum, glossary constants) live in `shared/`. Duplicating a schema definition elsewhere is a defect; the single definition is the wire format.

## 7. Naming and Layout

- Module names equal architecture element names (blueprint §5); renames are architecture changes.
- `test/offline/` mirrors module layout; `test/live/` contains only provider/network-dependent tests.
- New top-level directories anywhere in the repo require an architecture decision.
