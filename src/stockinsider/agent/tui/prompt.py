"""Terminal UI input: framed prompt, slash completion, status line, choices.

prompt_toolkit reads every answer the REPL asks for. The command prompt
completes slash commands from agent/repl's SLASH_COMMANDS, so the UI
has no verb of its own. Write confirmations use a dedicated two-option
prompt whose default is decline: only arrow keys or Tab move the
choice, Enter confirms it, and every other key is ignored, so neither a
single keystroke nor typed-ahead text can accept a write (INV-004).

Implements: REQ-SI-FR-026, REQ-SI-INV-004 (ADR-007)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame

from stockinsider.agent.repl import SlashCommand
from stockinsider.agent.tui.render import format_arguments

#: The answer a cancelled sub-prompt gives. Every existing sub-prompt
#: (the /watch candidate selection and [y/N], the /resume picker)
#: treats it as cancel; none treats it as a choice.
CANCEL_ANSWER = "q"

STYLE = Style.from_dict(
    {
        "prompt": "ansicyan bold",
        "placeholder": "ansibrightblack italic",
        "bottom-toolbar": "noreverse ansibrightblack",
        "frame.border": "ansibrightblack",
        "choice": "",
        "choice.selected": "ansicyan bold",
        "choice.hint": "ansibrightblack",
        "confirm.title": "ansiyellow bold",
    }
)

_DECLINE_LABEL = "No, do not execute it"
_ACCEPT_LABEL = "Yes, execute this write"


class SlashCompleter(Completer):
    """Completes the command word of a slash command from the REPL command table.

    Implements: REQ-SI-FR-026, REQ-SI-FR-013 (ADR-007)
    """

    def __init__(self, commands: Sequence[SlashCommand]) -> None:
        """Complete from these commands, in table order."""
        self._commands = tuple(commands)

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        """Yield `/name` candidates while the cursor is still in the first word.

        Implements: REQ-SI-FR-026 (ADR-007)
        """
        text = document.text_before_cursor
        if not text.startswith("/") or any(ch.isspace() for ch in text):
            return
        for command in self._commands:
            word = f"/{command.name}"
            if word.startswith(text):
                yield Completion(word, start_position=-len(text), display_meta=command.usage)


def toolbar_text(status: Mapping[str, Any]) -> str:
    """The status line: harness counters, an unreadable one shown as '?'.

    Implements: REQ-SI-FR-026, REQ-SI-INV-003 (ADR-007)
    """

    def _show(key: str) -> str:
        value = status.get(key)
        return "?" if value is None else str(value)

    return (
        f" {_show('session_id')} · {_show('profile')} · {_show('model')}"
        f" · tokens {_show('session_tokens')}/{_show('budget_tokens')}"
        f" · post-check {_show('last_verdict')}"
        f" · watchlist {_show('watchlist')} · calls left {_show('calls_remaining')}"
        "   / commands · ctrl+c clears · ctrl+d exits "
    )


def _main_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("c-c")
    def _clear_or_interrupt(event: KeyPressEvent) -> None:
        buffer = event.app.current_buffer
        if buffer.text:
            buffer.reset()
        else:
            event.app.exit(exception=KeyboardInterrupt())

    @bindings.add("escape", "enter")
    def _newline(event: KeyPressEvent) -> None:
        event.app.current_buffer.insert_text("\n")

    return bindings


def _sub_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("escape", eager=True)
    @bindings.add("c-c")
    @bindings.add("c-d")
    def _cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=CANCEL_ANSWER)

    return bindings


def confirmation_app(tool: str, arguments: Any) -> Application[bool]:
    """The default-decline choice for one proposed write.

    Up/Left select decline, Down/Right select accept, Tab toggles, Enter
    confirms the selection; Escape, Ctrl+C and Ctrl+D decline at once.
    Every other key is ignored, typed-ahead text included.

    Implements: REQ-SI-INV-004, REQ-SI-FR-026 (ADR-005 Am3, ADR-007)
    """
    accept = [False]

    def _choices() -> StyleAndTextTuples:
        rows: StyleAndTextTuples = []
        for value, label in ((False, _DECLINE_LABEL), (True, _ACCEPT_LABEL)):
            selected = accept[0] is value
            marker = "❯" if selected else " "
            rows.append(("class:choice.selected" if selected else "class:choice", f"{marker} {label}\n"))
        rows.append(("class:choice.hint", "up/down choose · enter confirms · esc declines"))
        return rows

    bindings = KeyBindings()

    @bindings.add("up")
    @bindings.add("left")
    def _select_decline(event: KeyPressEvent) -> None:
        accept[0] = False

    @bindings.add("down")
    @bindings.add("right")
    def _select_accept(event: KeyPressEvent) -> None:
        accept[0] = True

    @bindings.add("tab")
    @bindings.add("s-tab")
    def _toggle(event: KeyPressEvent) -> None:
        accept[0] = not accept[0]

    @bindings.add("enter")
    def _decide(event: KeyPressEvent) -> None:
        event.app.exit(result=accept[0])

    @bindings.add("escape", eager=True)
    @bindings.add("c-c")
    @bindings.add("c-d")
    def _decline(event: KeyPressEvent) -> None:
        event.app.exit(result=False)

    @bindings.add(Keys.Any)
    def _ignore(event: KeyPressEvent) -> None:
        return None

    title: StyleAndTextTuples = [
        ("class:confirm.title", "Execute this write proposed by the model?\n"),
        ("", f"  {tool} {format_arguments(arguments)}"),
    ]
    body = HSplit(
        [
            Window(FormattedTextControl(title), dont_extend_height=True),
            Window(FormattedTextControl(_choices, focusable=True, show_cursor=False), dont_extend_height=True),
        ]
    )
    return Application[bool](
        layout=Layout(Frame(body)),
        key_bindings=bindings,
        full_screen=False,
        erase_when_done=True,
        style=STYLE,
    )


class PromptUI:
    """The prompt_toolkit side of the terminal UI.

    Implements: REQ-SI-FR-026 (ADR-007)
    """

    def __init__(self, commands: Sequence[SlashCommand]) -> None:
        """Build the command and sub-prompt sessions (raises if no console is usable)."""
        self._status: Mapping[str, Any] = {}
        self._main: PromptSession[str] = PromptSession(
            message=[("class:prompt", "❯ ")],
            completer=SlashCompleter(commands),
            complete_while_typing=True,
            show_frame=True,
            bottom_toolbar=self._toolbar,
            key_bindings=_main_bindings(),
            history=InMemoryHistory(),
            placeholder=[("class:placeholder", "Ask about a symbol, or type / for commands")],
            erase_when_done=True,
            style=STYLE,
        )
        self._sub: PromptSession[str] = PromptSession(
            key_bindings=_sub_bindings(),
            show_frame=True,
            erase_when_done=True,
            style=STYLE,
        )

    def _toolbar(self) -> str:
        return toolbar_text(self._status)

    def read_main(self, status: Mapping[str, Any]) -> str:
        """Read the next command line under the given status line.

        Ctrl+C clears a non-empty line and raises KeyboardInterrupt on an
        empty one; Ctrl+D on an empty line raises EOFError.

        Implements: REQ-SI-FR-026 (ADR-007)
        """
        self._status = status
        return self._main.prompt()

    def read_sub(self, message: str) -> str:
        """Answer a dispatch sub-prompt; Escape, Ctrl+C and Ctrl+D answer CANCEL_ANSWER.

        Implements: REQ-SI-FR-026, REQ-SI-INV-004 (ADR-007)
        """
        return self._sub.prompt(message)

    def confirm_write(self, tool: str, arguments: Any) -> bool:
        """Ask the human to accept or decline one proposed write; decline is the default.

        Implements: REQ-SI-INV-004, REQ-SI-FR-026 (ADR-005 Am3, ADR-007)
        """
        return bool(confirmation_app(tool, arguments).run())
