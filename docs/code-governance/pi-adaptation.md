# pi Adaptation — Development Governance for pi Users

| Field | Value |
|---|---|
| Document | `docs/code-governance/pi-adaptation.md` (D3 companion — harness parity) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Related | `permission-model.md`; `.opencode/permissions.jsonc`; `.pi/extensions/governance-gate.ts` |

Team members may develop with **opencode** or **pi**. Governance must be harness-neutral: the same constraints apply regardless of tooling. This document maps each opencode-side artifact to its pi equivalent.

## 1. Mapping Table

| Concern | opencode artifact | pi equivalent | Parality notes |
|---|---|---|---|
| Entry-point instructions | `AGENTS.md` | **`AGENTS.md` (native)** | pi loads `AGENTS.md` from the project directory automatically (also global `~/.pi/agent/AGENTS.md` and parent dirs). One file serves both harnesses — this is why AGENTS.md is written harness-neutrally. |
| Machine-readable permissions | `.opencode/permissions.jsonc` | `.pi/extensions/governance-gate.ts` | The pi extension intercepts `tool_call` events and blocks `read` on no-access paths and `write`/`edit` outside RW paths. Executable enforcement, not declarative config — same matrix, different mechanism. |
| Always-on behavioral rules | `.opencode/rules.md` (human-only) | AGENTS.md §2 (non-negotiables) + §8 (stop-and-ask) | pi has no separate rules file; the rules live in the shared AGENTS.md and in `.agent/rules.md` (covenant). |
| Project covenant | `.agent/rules.md` | **`.agent/rules.md` (shared)** | Harness-independent by design. |
| Tool manifest | `docs/code-governance/mcp-tool-manifest.md` | Same document, §3 | pi's base tools (`read`/`write`/`edit`/`bash`) are gated by the extension; role discipline (plan/build/verify) is behavioral — pi sessions are single-role by convention. |
| Review backstops | branch protection, review memos, CI gates | **identical** | Harness-agnostic; this is the layer that guarantees parity even where mechanical enforcement differs. |

## 2. First-Run Setup (pi users)

1. pi prompts for **project trust** when it finds `.pi/` resources (`.pi/settings.json` trust flow). Trust the project to enable the governance-gate extension — refusing it leaves only the behavioral rules and the CI backstops, which is a degraded posture, not an acceptable one.
2. Verify the gate: ask the agent to edit any file under `docs/` — the call must be blocked with a governance reason. This check is part of onboarding and is recorded in the review memo of a member's first PR.

## 3. Enforcement Boundary (honest limits)

- The extension governs `read`/`write`/`edit` precisely (root-segment path classification, so runtime `data/` is never confused with `src/stockinsider/data/`).
- `bash` is governed **heuristically**: only unambiguous tokens (`.env`, `sessions/`). Documented as guard G4; the review memo and branch protection close the remainder.
- Role separation (plan/build/verify) is behavioral in pi. If a future need arises for hard role enforcement, project-local pi agents (`.pi/agents/`) can define scoped role agents — deferred to the option ledger, not built speculatively.

## 4. Parity Rule

Any change to `.opencode/permissions.jsonc`, `.opencode/rules.md`, or the permission model must be mirrored in this document's mapping and, where behavior differs, in `governance-gate.ts` — in the same change set. A governance change that updates one harness and not the other is a defect (review-memo check item).
