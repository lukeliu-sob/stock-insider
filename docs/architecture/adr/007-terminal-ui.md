# ADR-007 — Terminal UI: an opt-in inline front-end over the REPL dispatch

| Field | Value |
|---|---|
| ADR | 007 |
| Date | 2026-10-01 |
| Status | accepted (owner-approved with TP-021, 2026-10-01; decisions 1-7 taken in session the same day) |
| Related | REQ-SI-FR-026 (new); REQ-SI-FR-013, FR-019, INV-001, INV-004; ADR-001 (agent loop); ADR-005 Am3 (confirmation tokens, non-relay principle); ADR-006 (post-check); blueprint §5, §7.2, §7.3; TP-015 P0-1 (ASCII chrome) |
| Change set | TP-021 (`docs/test-plans/TP-021.md`) |

## Context

The REPL is a line loop over `input()` and `print()`: no completion, no
status, no visual separation between tool progress, verified answers and
errors. On 2026-10-01 the owner asked for a terminal UI in the style of
Claude Code and decided:

1. inline Claude-Code style, not a full-screen application;
2. a new dependency is acceptable;
3. the UI lives in `agent/tui/`;
4. opt-in first: the plain REPL stays the default;
5. answers render as Markdown;
6. Unicode chrome is allowed inside the UI (exemption from TP-015 P0-1);
7. the UI is a new requirement (REQ-SI-FR-026), not an amendment.

Three properties of the existing system constrain any UI:

- **Verify-then-display** (`agent/loop.py` H1, ADR-006): provider deltas
  buffer in the turn engine and reach the screen only after the numeric
  post-check passes; a quarantined original is never shown.
- **One verb set** (blueprint §7.3): slash commands and CLI subcommands
  are two entries to one verb set; a third verb set is forbidden.
- **Thread-bound storage**: the data store opens its SQLite connection
  with the default `check_same_thread=True`, so every data access must
  stay on the thread that opened it.

## 1. Decision

1. **Toolkit.** prompt_toolkit for input, Rich (already a dependency) for
   output. prompt_toolkit 3.0.53 provides the Claude-Code idioms
   directly: a framed input (`show_frame`), a completion menu while
   typing, a `bottom_toolbar` status line, `choice()` / `ChoiceInput`
   selection prompts, and pipe input for offline tests. Pin
   `prompt_toolkit>=3.0.53,<3.1`; its only runtime dependency is
   `wcwidth`.
2. **Placement.** `src/stockinsider/agent/tui/` is a presentation module
   of the REPL element (advisory surface). It imports agent modules and
   `shared` only and reaches data exclusively through the injected data
   store and registry tools, exactly as `agent/repl` does. The import
   gate already classifies it as agent tier; no gate change. `cli`
   remains the composition root and only selects the front-end.
3. **One dispatch core, two front-ends.** `agent/repl._session_loop`
   stays the only dispatcher. It talks to the user through an I/O port,
   `ReplIO` (ask, echo, progress, render, stream, status, turn started
   and finished, phase, pending write). `PlainIO` reproduces today's
   behavior byte for byte; `TuiIO` (in `agent/tui`) renders the same
   events. Slash completion and `/help` read one public command table in
   `agent/repl`. UI-only actions (clearing the input, the status line)
   are view operations, never verbs.
4. **Single-threaded.** Input, dispatch, the turn engine and output run
   on the main thread, as in the plain REPL. Rich's live activity
   indicator refreshes from its own thread but touches no application
   state. The data store stays on its thread; Ctrl+C during a turn raises
   KeyboardInterrupt into the existing `turn interrupted` path; no
   cancellation machinery is added to the engine or the provider.
5. **Activation.** Opt-in through `--ui tui` (root command, `analyze`,
   `resume`) or `STOCKINSIDER_UI=tui`; the default is `plain`. The UI
   starts only when stdin and stdout are terminals and a console can be
   opened. Otherwise an explicit notice names the reason and the plain
   REPL runs; the check happens before any session is opened. A missing
   dependency is an explicit error naming `prompt_toolkit` and
   `--ui plain` (INV-003: explicit, never silent).
6. **Display rules (INV-001 surface).**
   1. Model text reaches the screen only through the engine's `render()`
      and the post-check-gated stream replay. Nothing renders provider
      deltas live, and reasoning content is never displayed. During a
      turn the activity indicator shows a phase label (model, tool name,
      verifying, revising) and the elapsed time only.
   2. **Render fidelity.** An answer renders as Markdown only if the
      multiset of digit sequences in the rendered output equals that of
      the verified text; otherwise the literal text is shown. Links
      render with visible targets (Rich `hyperlinks=False`). Evidence
      (Rich 15.0.0, probed 2026-10-01): the ordered list `1. alpha` /
      `5. beta` renders as `1 alpha` / `2 beta`, so a number absent from
      the record appears; a link hides its URL (`.../2024` disappears);
      an HTML comment `<!-- 999 -->` is dropped.
   3. Harness chrome (status line, footers) shows harness counters only:
      session id, profile, model, token usage, tool count, verdict,
      watchlist size, call budget. No market data and no derived
      numbers; an unknown counter renders as `?`, never as a default.
7. **Write confirmation (INV-004).** A write the model proposes is
   reported by the engine (`on_pending_write`: token, tool, arguments)
   and shown after the turn as a choice prompt naming the exact tool and
   arguments. Decline is the default; Enter on the default, Escape and
   Ctrl+C decline; no single keystroke accepts. Accepting submits
   `confirm <token>` through the existing `_CONFIRM_LINE` path, so the
   broker, the single-use token and the session record are unchanged and
   the token still never transits model text (ADR-005 Am3). Pending
   prompts are dropped when the bound session changes. The `/watch` and
   `/resume` sub-prompts keep their text answers in phase 1; cancelling
   one (Escape, Ctrl+C) answers `q`, which every existing sub-prompt
   treats as cancel.
8. **Engine hooks.** `TurnEngine.run_turn` gains two optional callbacks,
   `on_phase(name, detail)` and `on_pending_write(token, tool,
   arguments)`. With both absent, behavior is unchanged. Neither alters
   buffering, the post-check, or what reaches `render` and `stream_sink`.
9. **Session lifecycle.** Ctrl+D, `/exit`, or a second Ctrl+C within
   2 s on an empty prompt end the loop through the existing EOF path:
   the session closes and the resume hint stays in the scrollback.
   `start_new_session` and `resume_session` close the session bound at
   the moment of an unexpected exception before re-raising, in both
   front-ends, so a crash no longer leaves a session `active`.
10. **Chrome.** Inside the UI, Unicode glyphs and box drawing are allowed
    (owner decision 6, exemption from TP-015 P0-1); the plain REPL keeps
    ASCII chrome. All UI text is English (GOV-001, FR-014).

## 2. Alternatives Considered

- **Full-screen Textual application (opencode style).** Rejected by the
  owner's style decision. Also: Textual's inline mode is not supported on
  Windows (the owner's platform), the alternate screen drops the
  transcript from the terminal scrollback, and its event loop pushes the
  blocking engine into a worker thread that conflicts with the
  thread-bound SQLite connection.
- **Rich-only polish, no new dependency.** Rejected: `input()` offers no
  completion menu, status line or selection prompt, which are the core
  of the requested experience.
- **Live token streaming.** Rejected: contradicts verify-then-display
  (INV-001, H1). Never to be reopened by relaxing the post-check.
- **Esc-to-interrupt through a worker thread.** Deferred: it needs a
  thread model for the data store and cooperative cancellation in the
  engine and the provider; Ctrl+C already interrupts.
- **Arrow-key pickers for `/watch add` and `/resume` in phase 1.**
  Deferred to phase 2: they change the INV-004 dispatch path
  (`_cmd_watch`) and need their own negative suite.
- **Placement in `cli/tui/`.** Rejected (owner decision 3): `cli` would
  stop being a thin shell and would gain direct data-facade access that
  the REPL itself does not have.

## 3. Consequences

- Two presentation surfaces over one dispatch: every later REPL change
  must keep `PlainIO` output identical (golden transcript test) and be
  visible in `TuiIO`.
- `/help` and completion share one command table. `/report`, dispatched
  today but missing from `/help`, becomes listed: the only intended
  change to plain output.
- Ctrl+C at the UI prompt clears the input instead of ending the
  process; plain-mode semantics are unchanged.
- Rich upgrades can change Markdown output. The fidelity check turns any
  digit-altering change into a literal fallback, and the adversarial
  render suite pins it (risk R-13).
- A pre-existing gap becomes more visible: runtime policy P-17 and
  memory-design §3 say an interrupted turn is marked `incomplete` and
  excluded from context, but the loop records nothing on interruption
  and the user message stays in history. The UI does not change this;
  it is recorded as DE-14.

## 4. Reopen Conditions

- The owner wants a multi-pane layout (sidebars, a session-browser
  pane): reconsider a full-screen toolkit, noting the Windows inline
  restriction.
- Ctrl+C proves insufficient for interruption: design a data-store
  thread model first, then cooperative cancellation.
- prompt_toolkit maintenance stalls, or a 3.1 release breaks the pinned
  API.
- Literal fallbacks become frequent in live use (owner observation; the
  fallback is display-only and not recorded in the session): consider a
  Markdown renderer that never renumbers lists.
