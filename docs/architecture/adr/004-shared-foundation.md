# ADR-004 — Shared Foundation: Cross-Module Types, Schemas, and Policy Constants

| Field | Value |
|---|---|
| ADR | 004 |
| Date | 2026-09-16 |
| Status | accepted (owner-approved with TP-004) |
| Related | `architecture-blueprint.md` §5; `docs/architecture/trace-matrix.md` (FR-014/GOV-001/SEC-003/GOV-005/FR-011 rows); permission-model guard G2 |
| Change set | TP-004 (`docs/test-plans/TP-004.md`) |

## 1. Decision

`src/stockinsider/shared/` is the **single authority** for cross-module wire types, schemas, and policy constants. TP-004 lands four modules:

1. `shared/language.py` — runtime English-policy helpers (`is_english_only`, `assert_english`; GOV-001/FR-014). The CI artifact gate stays authoritative for repository files; the helpers govern runtime output at render paths. Complementary by design.
2. `shared/egress.py` — the SEC-003 egress whitelist (static vendor domains) plus `validate_egress_url` (HTTPS-only, exact-or-subdomain match, fail-closed). Dynamically resolved endpoints (provider base URLs) are passed per-call via `extra_allowed`; they are configuration, not whitelist members.
3. `shared/provenance.py` — the authoritative GOV-005 stamp: field set, `ProvenanceStamp`, explicit-placeholder prefix, and `validate_provenance` (missing/blank/wrong-typed fields rejected).
4. `shared/events.py` — the authoritative FR-011 event kinds and `validate_event` (unknown kinds fail closed; `session-open` carries a record with validated provenance).

**Validation semantics are fail-closed everywhere** (INV-003 posture extended to the type layer): unknown event kinds, missing provenance fields, non-HTTPS schemes, and non-whitelisted hosts are explicit errors, never silent tolerance.

**Schema evolution is forward-only** (memory-design S6): kinds and fields are added, never repurposed; the shapes already on disk from TP-002/TP-003 are the authority this ADR describes — validate the existing form, not a new one.

**Operating protocol (G2 institutionalized)**: every future change to `shared/` requires a linked ADR and owner approval. The pi/opencode governance gates enforce path-level blocking; the propose–review–authorize cycle (proposals staged, owner-instructed application, AI-log record) is the sanctioned workflow. This ADR is the charter example.

## 2. Alternatives Considered

- **Schemas kept in their owning modules** (session defines its events, providers define stamps): rejected — cross-module wire formats drift silently; the BD-006 class of error (silent divergence) becomes structural. `shared/` existence is already promised by the blueprint module map and enforced by the import-boundary gate.
- **pydantic models for everything now**: rejected — adds a dependency before its payoff (nested validation, JSON Schema generation) is needed; stdlib dataclasses + explicit validators cover the current field counts. Reopen when tool I/O schemas arrive (TP-005) if the hand-written surface exceeds ~5 modules.
- **jsonschema runtime validation of events**: deferred, not rejected — the EventKind enum + hand checks match current complexity; a jsonschema document can be layered later without breaking the forward-only rule.

## 3. Consequences

- Every `shared/` change carries ADR ceremony (by design: it is a safety-critical path; the cost is the point).
- `agent/session` now validates stamps on creation (adoption): blank or wrong-typed provenance fails session creation — stricter than TP-002/003 behavior, aligned with GOV-005's zero-missing-fields fit criterion.
- The egress whitelist has no consumer yet; the HTTP choke point (SEC-003's S2 evidence) wires it when the data side lands. Until then `test_egress.py` holds the adversarial evidence.
- Registry (TP-005) and guardrail (TP-006) receive ready-made provenance and event types instead of inventing wire formats.

## 4. Reopen Conditions

- Tool I/O schema design (TP-005 / ADR-005) may extend `shared/` with a tool-envelope module — same protocol, linked ADR.
- pydantic adoption if hand-written validation surface grows past the threshold above.
- Chinese-alias symbol-map exception (FR-014's carve-out) lands with the symbol layer; `language.py` is not modified for it — the exception is enforced at the symbol layer.
- Egress whitelist growth (new vendors) rides with the data-side TPs that consume them; whitelist edits are `shared/` changes and follow this protocol.

## Amendment 1 (2026-09-23) — TP-012: the sanitizer enters shared/

`shared/sanitize.py` is the SEC-002 layer-one component
(news-filtering-design §6): the one legal common dependency of
`agent/context` and `data/ingest` for neutralizing instruction-like
content in untrusted headlines before they enter model context.
Semantics: total and deterministic (same input, same output; no
configuration surface); NFKC normalization collapses obfuscation
forms before pattern matching; control, zero-width and bidi
characters are stripped; a closed set of directive patterns and
role markers is replaced with the visible `[neutralized]` marker —
sanitization never silently rephrases. Storage keeps raw text
(evidence); only the egress path sanitizes. `has_active_directives`
provides the post-check used by the injection suite: any active
directive surviving the sanitizer is a sanitizer defect, not a
content judgment. Pattern-list changes are adversarial-suite-gated
(QA-002 discipline).

## Amendment 2 (2026-09-29, TP-018) — egress: model-runtime hosts, write-time config validation, no-bare-EgressViolationError

M9 (TP-017 PR-3b) put the provider layer behind the SEC-003
whitelist but shipped three defects found by the third audit:
`EgressViolationError` (a bare RuntimeError) escaped the REPL's
ProviderError handler and crashed the session into a stuck "active"
state; `config set --chat-base-url` accepted any URL and deferred
the failure to the first question; and OpenRouter-class endpoints
had no legal path. Corrected rules:

1. Fail-closed everywhere, crash nowhere: the provider wraps
   EgressViolationError into ProviderError with the host named; the
   REPL's conversational handler additionally catches
   EgressViolationError as defense in depth. A policy rejection is
   an explicit error line, never a session crash.
2. Write-time validation: `config set --chat-base-url` /
   `--embedding-base-url` validate against the whitelist before
   persisting; the error names the host and the extension path.
3. Extension surface: the `.env` entry
   `EGRESS_EXTRA_HOSTS` (comma-separated) extends the allowed set
   for provider endpoints at resolution time — an explicit,
   auditable owner decision, not a silent default (INV-003
   discipline).

Implements: REQ-SI-SEC-003.

## Amendment 3 (2026-09-29, TP-018b) — language allowlist design; loopback HTTP

Fourth-audit corrections to Am2's neighborhood (the language change
had shipped without an ADR of its own - a governance miss the audit
rightly flagged):

1. Runtime English-only (shared/language.py) is a positive allowlist:
   printable ASCII, Latin-1 supplement, Latin Extended-A, a closed
   typographic/arrows/comparison set, and a closed report-emoji set
   (check/cross/warning/chart up/down/bars + variation selector).
   The first cut omitted arrows, bullets and narrow no-break spaces
   the model genuinely uses in date ranges and lists; whole correct
   answers were withheld. Widening stays closed-set: anything not
   enumerated fails closed (Cyrillic, Hangul, Greek, CJK verified
   rejected).
2. Egress loopback exception: http:// (plain HTTP) is allowed when
   and only when the host is loopback (localhost, ::1, 127.0.0.0/8).
   Local model runtimes do not egress; refusing them made the
   documented local-endpoint path unusable. Non-loopback HTTP is
   still refused exactly as before.

Implements: REQ-SI-FR-014, REQ-SI-GOV-001, REQ-SI-SEC-003.

## Amendment 4 (2026-09-30, TP-019) — loopback is an address; the language policy checks scripts, not symbols

Fifth-audit corrections to Am3:

1. Loopback correction. Am3 decided "localhost, ::1, 127.0.0.0/8";
   the code shipped `host.startswith("127.")`, a string-prefix test.
   DNS names such as `127.attacker.example` or `127.0.0.1.nip.io`
   (which resolve anywhere) therefore skipped BOTH the HTTPS rule and
   the whitelist, and a provider key would have travelled in cleartext
   to an arbitrary host. Loopback is now an address property: a host
   is loopback only when it is the name `localhost` or parses as an IP
   literal with `is_loopback` (127.0.0.0/8, ::1). Every other hostname
   is remote and follows the unchanged HTTPS + whitelist rules. The
   RM-55 statement "loopback HTTP is scoped to 127/8 + localhost + ::1"
   described the decision, not the shipped code; RM-56 records the
   erratum.
2. Language policy by script. Am3's closed character set kept
   withholding whole correct answers for a checkmark, a triangle, a
   thin space, a common emoji or a sigma (two consecutive audits). The
   policy governs LANGUAGE, and language is carried by letters and
   digits. The runtime check now: accepts letters only from Latin
   blocks plus a closed set of Greek letters used as finance/math
   symbols (alpha, beta, gamma, delta, Delta, sigma, Sigma, mu, pi);
   accepts only ASCII digits; rejects CJK ideographs, CJK punctuation
   and fullwidth forms, control characters and invisible format
   characters (bidi overrides could disguise text; the emoji joiners
   ZWJ/ZWNJ excepted); and accepts everything else (punctuation,
   symbols, arrows, math and currency signs, emoji, separators).
   Am3's allowlist remains the fast path. Greek words, Cyrillic,
   Hangul, Arabic, Hebrew, Devanagari, Thai and non-ASCII digits fail
   closed (TP-019 negative suite).

Implements: REQ-SI-SEC-003, REQ-SI-FR-014, REQ-SI-GOV-001.

## Amendment 5 (2026-10-04, TP-029) — the interrupted-turn marker: `turn-incomplete`

DE-14 (runtime policy P-17, memory-design §3): a turn interrupted
before its answer is recorded with status `incomplete` and left out of
context reconstruction. The loop recorded nothing, so the dangling
question replayed on the next turn.

Decision: `EventKind` gains `TURN_INCOMPLETE = "turn-incomplete"`. The
event carries the turn id and nothing else. The turn engine appends it
only when a `KeyboardInterrupt` arrives after the turn's user message
and before its answer (TP-029). The change is additive under the
forward-only rule above: no existing kind or field changes, and
sessions written before this amendment read unchanged. Like the other
kinds, the marker gets no payload checks beyond the kind itself.

Alternatives considered (owner decision, 2026-10-04, from a three-option
question):
- Reuse `error` with `kind: "interrupted"`: no new kind, but `error`
  means a failure, and a user interrupt is not one. Not chosen.
- A reader-side rule with no marker: covers a hard crash too, but
  writes nothing to session.jsonl, so the record stays implicit. Not
  chosen as the sole mechanism.

Residual, not closed here: a hard crash (process killed, power loss)
runs no handler, so it writes no marker. P-17 names crashes; covering
them is a separate decision.

Implements: REQ-SI-FR-011, REQ-SI-INV-003.
