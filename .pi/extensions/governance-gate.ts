/**
 * Governance Gate — pi adaptation of .opencode/permissions.jsonc
 * =====================================================================
 * Stock Insider, course deliverable D3 (harness adaptation).
 *
 * Encodes docs/architecture/permission-model.md as executable rules:
 * intercepts tool_call events and blocks access that the permission
 * matrix forbids. Counterpart of the opencode permissions file, for
 * team members who use pi instead of opencode.
 *
 * Classification is root-segment based (paths are relativized against
 * process.cwd()), so the runtime state directory `data/` is NOT confused
 * with the source module `src/stockinsider/data/`.
 *
 * Scope notes (honest limits):
 *  - Bash commands are governed heuristically (G4): only unambiguous
 *    tokens are checked (.env, sessions/). Full bash analysis is out of
 *    scope; branch protection and review memos remain the backstop.
 *  - Role discipline (plan/build/verify) is behavioral in pi (single-
 *    role sessions by convention, AGENTS.md 3-8). This gate enforces
 *    path rules regardless of role.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Directories at repo root with no access for any coding-agent role. */
const NO_ACCESS_DIRS = ["sessions", "data"];
/** Root files with no access. */
const NO_ACCESS_FILES = [".env"];
/** Directories at repo root that are read-only for the coding agent. */
const READ_ONLY_DIRS = ["docs", "prompts", ".github", "transcripts", ".opencode", ".agent", ".pi"];
/** Root files that are read-only for the coding agent. */
const READ_ONLY_FILES = [
	"AGENTS.md",
	"Prompt.md",
	"Report.md",
	"architecture-blueprint.md",
	"README.md",
];
/**
 * Safety-critical source prefixes: writable in principle, but every change
 * requires a linked ADR and human approval (permission-model guard G2).
 * The gate blocks agent-authored writes; the owner edits these directly.
 */
const SAFETY_CRITICAL_PREFIXES = [
	"src/stockinsider/agent/guardrail",
	"src/stockinsider/agent/registry",
	"src/stockinsider/shared",
];

type Access = "no-access" | "read-only" | "safety-critical" | "rw";

/** Normalize separators and relativize against cwd. */
function toRepoRelative(rawPath: string): string {
	const norm = rawPath.replace(/\\/g, "/").replace(/^\.\//, "");
	const cwd = process.cwd().replace(/\\/g, "/");
	if (norm.startsWith(cwd + "/")) {
		return norm.slice(cwd.length + 1);
	}
	return norm;
}

function classify(rel: string): Access {
	const root = rel.split("/")[0];
	if (NO_ACCESS_DIRS.includes(root) || NO_ACCESS_FILES.includes(root)) return "no-access";
	if (READ_ONLY_DIRS.includes(root) || READ_ONLY_FILES.includes(root)) return "read-only";
	if (SAFETY_CRITICAL_PREFIXES.some((p) => rel.startsWith(p))) return "safety-critical";
	return "rw";
}

function reason(access: Access, path: string): string {
	switch (access) {
		case "no-access":
			return `Governance gate: "${path}" is runtime state or secrets — no access for the coding agent (permission model N).`;
		case "read-only":
			return `Governance gate: "${path}" is owner-authored (permission model R). Propose changes to the owner; do not write directly.`;
		case "safety-critical":
			return `Governance gate: "${path}" is a safety-critical path. Changes require a linked ADR and human approval (guard G2); the owner applies them.`;
		default:
			return "";
	}
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		const tool = event.toolName;

		// --- read tool: block no-access paths (secrets, runtime state) ---
		if (tool === "read") {
			const rel = toRepoRelative(String(event.input.path ?? ""));
			const access = classify(rel);
			if (access === "no-access") {
				if (ctx.hasUI) ctx.ui.notify(`Blocked read: ${rel}`, "warning");
				return { block: true, reason: reason(access, rel) };
			}
			return undefined;
		}

		// --- write/edit tools: enforce the full matrix ---
		if (tool === "write" || tool === "edit") {
			const rel = toRepoRelative(String(event.input.path ?? ""));
			const access = classify(rel);
			if (access !== "rw") {
				if (ctx.hasUI) ctx.ui.notify(`Blocked ${tool}: ${rel}`, "warning");
				return { block: true, reason: reason(access, rel) };
			}
			return undefined;
		}

		// --- bash: heuristic guard G4 (unambiguous tokens only) ---
		if (tool === "bash") {
			const command = String(event.input.command ?? "");
			const hit = [".env", "sessions/"].find((token) => command.includes(token));
			if (hit) {
				if (ctx.hasUI) ctx.ui.notify(`Blocked bash (contains "${hit}")`, "warning");
				return {
					block: true,
					reason: `Governance gate: bash command touches protected "${hit}" (runtime state / secrets). See mcp-tool-manifest G4.`,
				};
			}
			return undefined;
		}

		return undefined;
	});
}
