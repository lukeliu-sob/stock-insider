"""Terminal UI output: Rich rendering of the REPL's events.

Every line goes out as a Rich Text object, never as a markup string, so
model or data text containing "[...]" is shown verbatim. Answers come
only from the post-check-gated replay and render under the fidelity
rule. The activity indicator shows a phase label and the elapsed time,
never provider text (INV-001). Styles only color lines; they never
change the words.

Implements: REQ-SI-FR-026, REQ-SI-FR-019, REQ-SI-INV-001 (ADR-007)
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from rich import box
from rich.console import Console, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from stockinsider.agent.tui.fidelity import answer_renderable

_PHASE_LABELS = {
    "model": "Thinking",
    "verifying": "Verifying numbers (INV-001)",
    "revising": "Revising the draft (INV-002)",
}

_RED = ("error", "unknown command", "confirmed but failed")
_YELLOW = (
    "not found",
    "cancelled",
    "resume cancelled",
    "turn interrupted",
    "report not stored",
    "unknown or already-used token",
    "closing the session",
)
_GREEN = ("confirmed:", "added ", "removed ", "report stored")
_DIM = ("session ", "resume with:")


def phase_label(name: str, detail: str) -> str:
    """The activity label for a turn-engine phase; a tool phase names the tool.

    Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
    """
    if name == "tool":
        return f"Running {detail}" if detail else "Running a tool"
    return _PHASE_LABELS.get(name, "Working")


def line_style(line: str) -> str:
    """Color for a dispatch line, chosen by its leading words.

    Implements: REQ-SI-FR-026 (ADR-007)
    """
    text = line.lstrip()
    if text.startswith(_RED):
        return "red"
    if text.startswith(_YELLOW):
        return "yellow"
    if text.startswith(_GREEN):
        return "green"
    if text.startswith(_DIM):
        return "dim"
    return ""


def progress_style(line: str) -> str:
    """Color for an engine progress line (tool lines, footer, pending write, unverified notices).

    Implements: REQ-SI-FR-019, REQ-SI-FR-026, REQ-SI-INV-001 (ADR-007, ADR-008)
    """
    if line.startswith(("pending write confirmation", "unverified")) or "contained unverified numbers" in line:
        return "yellow"
    if "… failed" in line:
        return "red"
    return "dim"


def format_arguments(arguments: Any) -> str:
    """Tool arguments as the engine shows them (sorted JSON).

    Implements: REQ-SI-INV-004, REQ-SI-FR-026 (ADR-005 Am3, ADR-007)
    """
    try:
        return json.dumps(arguments, sort_keys=True)
    except (TypeError, ValueError):
        return repr(arguments)


def _gutter(glyph: str, style: str, body: RenderableType) -> Table:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=1, no_wrap=True)
    grid.add_column()
    grid.add_row(Text(glyph, style=style), body)
    return grid


class Activity:
    """The spinner line of a running turn: phase label, elapsed time, interrupt hint.

    Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
    """

    def __init__(self, clock: Callable[[], float]) -> None:
        """Start timing now; the first phase is the model call."""
        self._clock = clock
        self._started = clock()
        self._label = phase_label("model", "")
        self._spinner = Spinner("dots", style="cyan")

    @property
    def label(self) -> str:
        """The current phase label.

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        return self._label

    def set_phase(self, name: str, detail: str) -> None:
        """Show a new phase.

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        self._label = phase_label(name, detail)

    def __rich__(self) -> RenderableType:
        elapsed = int(self._clock() - self._started)
        self._spinner.update(
            text=Text.assemble(
                (f"{self._label}… ", "bold"),
                (f"{elapsed}s · ctrl+c to interrupt", "dim"),
            )
        )
        return self._spinner


class Screen:
    """The Rich output side of the terminal UI.

    Implements: REQ-SI-FR-026 (ADR-007)
    """

    def __init__(self, console: Console | None = None, *, clock: Callable[[], float] = time.monotonic) -> None:
        """Write to the given console (tests pass a recording one)."""
        self.console = console if console is not None else Console(highlight=False)
        self._clock = clock
        self._activity: Activity | None = None
        self._live: Live | None = None

    @property
    def activity_label(self) -> str | None:
        """The running turn's phase label; None when no turn runs.

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        return None if self._activity is None else self._activity.label

    def welcome(self, version: str) -> None:
        """The opening panel: product, version, the three keys that matter.

        Implements: REQ-SI-FR-026 (ADR-007)
        """
        body = Text.assemble(
            ("Stock Insider", "bold"),
            f" {version}\n",
            ("Analysis only; never trades.", "dim"),
            "\n",
            ("/help lists commands · ctrl+d exits · ctrl+c interrupts a turn", "dim"),
        )
        self.console.print(Panel(body, box=box.ROUNDED, border_style="cyan", expand=False))

    def line(self, text: str) -> None:
        """One dispatch line (command output, notices, errors).

        Implements: REQ-SI-FR-026, REQ-SI-INV-003 (ADR-007)
        """
        self.console.print(Text(text, style=line_style(text)))

    def progress(self, text: str) -> None:
        """One engine progress line, indented under the turn.

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        self.console.print(Text("  " + text, style=progress_style(text)))

    def notice(self, text: str) -> None:
        """The engine's final text when it replaced the answer (degraded, refused, stopped).

        Implements: REQ-SI-INV-001, REQ-SI-INV-003, REQ-SI-FR-026 (ADR-007)
        """
        self.console.print()
        self.console.print(_gutter("!", "bold yellow", Text(text, style="yellow")))

    def answer(self, text: str) -> None:
        """A verified answer: Markdown under the fidelity rule, else literal text.

        Implements: REQ-SI-FR-026, REQ-SI-INV-001 (ADR-007)
        """
        renderable, _is_markdown = answer_renderable(text)
        self.console.print()
        self.console.print(_gutter("●", "cyan", renderable))

    def user_line(self, text: str) -> None:
        """Echo the submitted input into the scrollback.

        Implements: REQ-SI-FR-026 (ADR-007)
        """
        self.console.print()
        self.console.print(Text.assemble(("❯ ", "bold cyan"), (text, "bold")))

    def sub_answer(self, prompt: str, answer: str) -> None:
        """Echo a sub-prompt and its answer.

        Implements: REQ-SI-FR-026 (ADR-007)
        """
        self.console.print(Text(f"{prompt}{answer}", style="dim"))

    def hint(self, text: str) -> None:
        """A transient usage hint.

        Implements: REQ-SI-FR-026 (ADR-007)
        """
        self.console.print(Text(text, style="dim italic"))

    def declined(self, tool: str, arguments: Any) -> None:
        """Record on screen that a proposed write was declined.

        Implements: REQ-SI-INV-004, REQ-SI-FR-026 (ADR-007)
        """
        self.console.print(
            Text(f"declined: {tool} {format_arguments(arguments)} was not executed", style="yellow")
        )

    def start_activity(self) -> None:
        """Show the activity indicator for a new turn.

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        self.stop_activity()
        self._activity = Activity(self._clock)
        self._live = Live(self._activity, console=self.console, transient=True, refresh_per_second=10)
        self._live.start()

    def set_phase(self, name: str, detail: str) -> None:
        """Update the running turn's phase label.

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        if self._activity is not None:
            self._activity.set_phase(name, detail)

    def stop_activity(self) -> None:
        """Remove the activity indicator (transient: nothing stays behind).

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        if self._live is not None:
            self._live.stop()
        self._live = None
        self._activity = None
