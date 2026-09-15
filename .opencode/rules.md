# .opencode/rules.md — Always-On Behavioral Rules (HUMAN-ONLY FILE)

> This file is authored and modified by humans only. The coding agent reads it as a
> constraint. Changes require owner approval. Counterpart for pi users: the same rules
> are stated in AGENTS.md §2/§8 and enforced by `.pi/extensions/governance-gate.ts`.

1. Follow the AGENTS.md reading protocol before every task; do not bulk-read artifacts.
2. Never write to read-only zones (`docs/`, `prompts/`, `.github/`, runtime state); never read secrets.
3. Obey the stop-and-ask list (AGENTS.md §8) — registry, architecture, prompts, CI, safety-critical paths, new dependencies, new modules, invariant enforcement points.
4. English only in everything you produce.
5. Update the AI-use log in the same change set as any code or prompt change.
6. The registry is append-only; a failing old test is a regression — fix code, never tests.
7. Every feature ships at least one negative/adversarial test.
8. Do not introduce dependencies, frameworks, or abstraction layers without an architecture decision.
9. When uncertain about scope or authority, stop and ask; guessing is the defect.
