"""TuiIO: the terminal UI's implementation of the REPL I/O port.

The dispatch loop in agent/repl drives everything; TuiIO only decides
how its events look. Replay deltas, already gated by the engine's
post-check, are buffered and rendered as one answer block once the
turn's next event arrives; nothing renders before the engine releases
it, and an interrupted turn shows no partial answer (INV-001). A write
the model proposed is asked about before the next command prompt,
through a default-decline choice whose accept submits `confirm <token>`
to the unchanged confirmation path (INV-004).

Implements: REQ-SI-FR-026, REQ-SI-INV-001, REQ-SI-INV-004 (ADR-007)
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from rich.console import Console

from stockinsider import __version__
from stockinsider.agent.repl import SLASH_COMMANDS, ReplIO
from stockinsider.agent.tui import TuiUnavailable
from stockinsider.agent.tui.prompt import PromptUI
from stockinsider.agent.tui.render import Screen

#: Two Ctrl+C presses on an empty prompt within this window exit.
EXIT_WINDOW_SECONDS = 2.0


class TuiIO(ReplIO):
    """The terminal UI behind the REPL I/O port.

    Implements: REQ-SI-FR-026, REQ-SI-INV-001, REQ-SI-INV-004 (ADR-007)
    """

    def __init__(self, prompt: PromptUI, screen: Screen, *, clock: Callable[[], float] = time.monotonic) -> None:
        """Bind the input and output sides; the clock times the Ctrl+C window."""
        self._prompt = prompt
        self._screen = screen
        self._clock = clock
        self._stream: list[str] = []
        self._pending: list[tuple[str, str, Any]] = []
        self._status: Mapping[str, Any] = {}
        self._session_id: Any = None
        self._last_interrupt: float | None = None

    @classmethod
    def create(cls, *, console: Console | None = None, clock: Callable[[], float] = time.monotonic) -> TuiIO:
        """Build the UI; a console that cannot host prompt_toolkit raises TuiUnavailable.

        Implements: REQ-SI-FR-026, REQ-SI-INV-003 (ADR-007)
        """
        screen = Screen(console, clock=clock)
        try:
            prompt = PromptUI(SLASH_COMMANDS)
        except Exception as exc:  # noqa: BLE001 - any console failure means: no UI here
            raise TuiUnavailable(f"console unavailable: {type(exc).__name__}: {exc}") from exc
        return cls(prompt, screen, clock=clock)

    @property
    def screen(self) -> Screen:
        """The output side (tests read its activity state).

        Implements: REQ-SI-FR-026 (ADR-007)
        """
        return self._screen

    def welcome(self) -> None:
        """Print the opening panel.

        Implements: REQ-SI-FR-026 (ADR-007)
        """
        self._screen.welcome(__version__)

    def ask(self, prompt: str, *, main: bool) -> str:
        """Read the next answer; pending write confirmations come first.

        Implements: REQ-SI-FR-026, REQ-SI-INV-004 (ADR-007)
        """
        self._flush_answer()
        if not main:
            answer = self._prompt.read_sub(prompt)
            self._screen.sub_answer(prompt, answer)
            return answer
        while self._pending:
            token, tool, arguments = self._pending.pop(0)
            if self._prompt.confirm_write(tool, arguments):
                return f"confirm {token}"
            self._screen.declined(tool, arguments)
        while True:
            try:
                line = self._prompt.read_main(self._status)
            except KeyboardInterrupt:
                now = self._clock()
                if self._last_interrupt is not None and now - self._last_interrupt <= EXIT_WINDOW_SECONDS:
                    raise EOFError from None
                self._last_interrupt = now
                self._screen.hint("press ctrl+c again to exit, or ctrl+d")
                continue
            self._last_interrupt = None
            if line.strip():
                self._screen.user_line(line)
            return line

    def echo(self, line: str) -> None:
        """Show one dispatch line.

        Implements: REQ-SI-FR-026 (ADR-007)
        """
        self._flush_answer()
        self._screen.line(line)

    def progress(self, line: str) -> None:
        """Show one engine progress line.

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        self._flush_answer()
        self._screen.progress(line)

    def render(self, text: str) -> None:
        """Show the engine's replacement text (degraded, refused, stopped).

        Implements: REQ-SI-INV-001, REQ-SI-FR-026 (ADR-007)
        """
        self._flush_answer()
        self._screen.notice(text)

    def stream(self, piece: str) -> None:
        """Buffer one post-check-gated replay delta.

        Implements: REQ-SI-INV-001, REQ-SI-FR-026 (ADR-007)
        """
        self._stream.append(piece)

    def status(self, snapshot: Callable[[], dict[str, Any]]) -> None:
        """Take the status counters; a new bound session drops stale confirmations.

        Implements: REQ-SI-FR-026, REQ-SI-INV-004 (ADR-007)
        """
        current = snapshot()
        if current.get("session_id") != self._session_id:
            self._pending.clear()
            self._session_id = current.get("session_id")
        self._status = current

    def turn_started(self) -> None:
        """Start the activity indicator.

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        self._stream.clear()
        self._screen.start_activity()

    def turn_finished(self, outcome: Any | None) -> None:
        """Stop the indicator; an interrupted or failed turn shows no partial answer.

        Implements: REQ-SI-FR-019, REQ-SI-INV-001, REQ-SI-FR-026 (ADR-007)
        """
        if outcome is None:
            self._stream.clear()
        else:
            self._flush_answer()
        self._screen.stop_activity()

    def phase(self, name: str, detail: str) -> None:
        """Show the engine's current phase.

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        self._screen.set_phase(name, detail)

    def pending_write(self, token: str, tool: str, arguments: Any) -> None:
        """Queue a proposed write for a confirmation choice before the next prompt.

        Implements: REQ-SI-INV-004, REQ-SI-FR-026 (ADR-005 Am3, ADR-007)
        """
        self._pending.append((token, tool, arguments))

    def _flush_answer(self) -> None:
        if not self._stream:
            return
        text = "".join(self._stream).strip()
        self._stream.clear()
        if text:
            self._screen.answer(text)
