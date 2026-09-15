# MCP Tool Manifest — Stock Insider (Development-Time)

| Field | Value |
|---|---|
| Document | `docs/code-governance/mcp-tool-manifest.md` (course deliverable D3) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Related | `permission-model.md`; `architecture-blueprint.md` §9.3 |

**Scope**: the tools the **coding agent** (opencode / pi) may call during development. This is distinct from the **runtime tool registry** of the Stock Insider agent itself (blueprint §4.1) — the two manifests are never conflated; a pull request that confuses them fails structural review.

## 1. Tool × Role Matrix

| Tool | Plan | Build | Verify | Constraints |
|---|---|---|---|---|
| `read` | ✔ | ✔ | ✔ | Never on N-paths (`sessions/`, `data/`, `.env`) |
| `grep` / `find` / `ls` | ✔ | ✔ | ✔ | — |
| `write` / `edit` | ✖ | ✔ | ✖ | Within the permission matrix only (R-paths and safety-critical subpaths block) |
| `bash` | ✖ | ✔ | ✔ | Build: package/test commands only. Verify: test runner, coverage, lint. No network beyond package registry. |
| `web_search` / `fetch` | ✔ (documentation lookup only) | ✔ (dependency research; new dependencies still need ADR per `.agent/rules.md`) | ✖ | Never feeds content directly into artifacts without source citation |
| MCP servers (if configured) | none by default | none by default | none by default | Any additional MCP server requires a manifest change + owner approval |

## 2. Rules

1. **Default deny**: any tool not listed is unavailable; adding one requires a manifest change and owner approval (stop-and-ask, AGENTS.md §8).
2. The Plan role produces plans and diffs-in-prose only; it writes nothing.
3. The Verify role writes no repository content; its outputs are test results and review-memo inputs.
4. Bash commands may not touch `sessions/` or `data/` (runtime state) or `.env` (secrets) — heuristic enforcement in pi's governance gate; hard enforcement by review.
5. No tool use may bypass the egress expectations: development-time network access is limited to the package registry and documentation lookups.

## 3. Harness Encoding

- **opencode**: this matrix is encoded in `.opencode/permissions.jsonc` (tool capabilities per role + path rules + guards).
- **pi**: `read`/`write`/`edit`/`bash` gating is encoded in `.pi/extensions/governance-gate.ts`; role discipline is behavioral (AGENTS.md §3–8) since pi sessions are single-role by convention. Mapping details: `docs/code-governance/pi-adaptation.md`.
