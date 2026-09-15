# tools/checks — Structural-tier verification scripts

Each script is standalone, standard-library-only unless noted, exits
non-zero on failure, and is wired into `.github/workflows/ci.yml`
(mapping: `docs/code-governance/verification-constraints.md` §3).

| Script | Gate | Notes |
|---|---|---|
| `registry_schema.py` | D7-3 schema | needs `pyyaml`, `jsonschema`; also checks ID uniqueness and depends_on integrity |
| `trace_coverage.py` | R1 coverage | per-ID set equality between registry and trace matrix |
| `language_policy.py` | GOV-001 | CJK forbidden outside the documented exemptions |
| `docstring_ids.py` | R3 traceability | `Implements:` lines with valid registry IDs; no-op until src/ lands [DE-05] |
| `import_boundaries.py` | fitness function | blueprint §5 dependency direction; no-op until src/ lands [DE-05] |
| `secret_scan.py` | D7-2 (partial) | pattern-level; GitHub push protection remains the outer layer |
| `aiuse_gate.py` | D7-6 | needs `CI_BASE_SHA` (CI provides; local mode skips) |
| `testplan_gate.py` | D7-1 / GOV-006 | needs `CI_BASE_SHA` + `PR_BODY`; validates the referenced TP is approved |
| `parity_gate.py` | governance parity | permission-side changes require `pi-adaptation.md` in the same change set |

Run locally:

```bash
python tools/checks/registry_schema.py   # etc.
```

Guard discipline: scripts marked [DE-05] pass with a note until
scaffolding lands; their activation is part of the guard-removal PRs
(verification-constraints §4).
