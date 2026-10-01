"""TP-021: terminal UI units - render fidelity, completion, status line, activity.

Implements: REQ-SI-FR-026, REQ-SI-INV-001, REQ-SI-INV-003 (ADR-007)
"""

from __future__ import annotations

import ast
import io
from pathlib import Path
from typing import Any

from prompt_toolkit.application import create_app_session
from prompt_toolkit.buffer import CompletionState
from prompt_toolkit.completion import CompleteEvent, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console
from rich.markdown import Markdown

from stockinsider.agent import repl as repl_module
from stockinsider.agent.profiles import envelope_for
from stockinsider.agent.repl import _NOT_IMPLEMENTED, SLASH_COMMANDS, _cmd_help, _status_snapshot
from stockinsider.agent.session import SessionStore
from stockinsider.agent.tui.fidelity import answer_renderable, digit_sequences, rendered_text
from stockinsider.agent.tui.prompt import PromptUI, SlashCompleter, toolbar_text
from stockinsider.agent.tui.render import Activity, Screen, phase_label


def _shows(text: str) -> tuple[bool, str]:
    renderable, is_markdown = answer_renderable(text)
    return is_markdown, rendered_text(renderable)


def test_markdown_kept_when_digits_preserved() -> None:
    text = (
        "## 0700.HK on 2026-09-30\n\n"
        "**Close:** 412.6 HKD\n\n"
        "- RSI(14): 55.2\n"
        "- volume `12345678`\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        "| ROE | 21.3% |\n"
    )
    is_markdown, shown = _shows(text)
    assert is_markdown is True
    assert digit_sequences(shown) == digit_sequences(text)
    assert "**" not in shown and "|---|" not in shown  # rendered, not printed as source


def test_renumbered_ordered_list_falls_back_to_literal() -> None:
    kept, shown = _shows("1. alpha\n2. beta")
    assert kept is True  # boundary: a list Rich numbers exactly as written stays Markdown
    assert digit_sequences(shown) == digit_sequences("1. alpha\n2. beta")
    for text in ("1. alpha\n5. beta", "1. alpha\n3. beta"):  # Rich would show 1 and 2
        is_markdown, shown = _shows(text)
        assert is_markdown is False, text
        assert digit_sequences(shown) == digit_sequences(text)
        assert shown.strip() == text


def test_hidden_content_falls_back_to_literal() -> None:
    for text, hidden in (
        ("Close was 412.6 <!-- 999 --> today.", "999"),
        ('Close <span data-ref="555">412.6</span> HKD', "555"),
    ):
        assert hidden not in rendered_text(Markdown(text, hyperlinks=False))  # Rich hides it
        is_markdown, shown = _shows(text)
        assert is_markdown is False, text
        assert hidden in shown
        assert digit_sequences(shown) == digit_sequences(text)


def test_link_targets_stay_visible() -> None:
    text = "See [the filing](http://example.com/q/2024) for details."
    is_markdown, shown = _shows(text)
    assert is_markdown is True
    assert "http://example.com/q/2024" in shown


def _complete(text: str) -> list[str]:
    completer = SlashCompleter(SLASH_COMMANDS)
    return [c.text for c in completer.get_completions(Document(text), CompleteEvent())]


def test_completion_equals_command_table() -> None:
    assert _complete("/") == [f"/{command.name}" for command in SLASH_COMMANDS]
    assert _complete("/wa") == ["/watch"]
    assert _complete("/re") == ["/resume", "/report"]
    for text in ("", "hello", "watch", "/watch li", "/bogus"):
        assert _complete(text) == [], text


def _dispatched_names() -> set[str]:
    """Every slash name the dispatch loop compares against, read from its source."""
    tree = ast.parse(Path(repl_module.__file__).read_text(encoding="utf-8"))
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_dispatch_loop")
    names: set[str] = set()
    for node in ast.walk(loop):
        if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and len(node.ops) == 1):
            continue
        comparator = node.comparators[0]
        if not (isinstance(node.ops[0], ast.Eq) and isinstance(comparator, ast.Constant)):
            continue
        if node.left.id == "name":
            names.add(comparator.value)
        elif node.left.id == "line" and str(comparator.value).startswith("/"):
            names.add(comparator.value[1:])
    return names


def test_command_table_matches_dispatch() -> None:
    table = {command.name for command in SLASH_COMMANDS}
    assert table == _dispatched_names()
    assert not table & set(_NOT_IMPLEMENTED)  # unimplemented commands are never offered
    shown: list[str] = []
    _cmd_help(shown.append)
    help_text = "\n".join(shown)
    assert "/report <canonical-symbol>" in help_text
    for hidden in ("/compact", "/config", "/help"):
        assert hidden not in help_text


class _Watch:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def list(self) -> list[dict]:
        return self._rows


class _DataStore:
    def __init__(self, rows: list[dict], remaining: int) -> None:
        self.watchlist = _Watch(rows)
        self._remaining = remaining

    def sync_status(self) -> dict:
        return {"budget": {"remaining": self._remaining}}


class _BrokenDataStore:
    @property
    def watchlist(self) -> _Watch:
        raise RuntimeError("database is locked")

    def sync_status(self) -> dict:
        raise RuntimeError("database is locked")


def test_status_line_shows_harness_counters_only(tmp_path) -> None:
    store = SessionStore(root=tmp_path / "sessions")
    record = store.create(
        profile="standard",
        provenance={"model_id": "test-model", "provider_config": "u", "prompt_version": "identity-v1"},
    )
    budget = envelope_for("standard").max_session_tokens
    rows = [{"canonical_symbol": "0700.HK"}, {"canonical_symbol": "AAPL.US"}]
    line = toolbar_text(_status_snapshot(store, record, _DataStore(rows, 18)))
    for part in (
        record["session_id"],
        "standard",
        "test-model",
        f"tokens 0/{budget}",
        "post-check none",
        "watchlist 2",
        "calls left 18",
    ):
        assert part in line, part
    broken = toolbar_text(_status_snapshot(store, record, _BrokenDataStore()))
    assert "watchlist ?" in broken and "calls left ?" in broken
    assert "watchlist 0" not in broken and "calls left 0" not in broken  # unknown is never a default
    store.append_event(
        record["session_id"],
        {
            "event": "assistant-message",
            "text": "x",
            "turn": "turn-0001",
            "post_check": "failed",
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
    )
    after = toolbar_text(_status_snapshot(store, record, None))
    assert f"tokens 10/{budget}" in after and "post-check failed" in after and "watchlist ?" in after


def _frames(session: Any) -> list[tuple[int, str]]:
    """Record (frame height, the row right under the frame) at every render of a prompt.

    DummyOutput reports 40 rows below the cursor, as a real console does,
    so the layout is free to stretch into them.
    """
    seen: list[tuple[int, str]] = []

    def _measure(app: Any) -> None:
        screen = app.renderer._last_screen  # test-only look at the rendered rows
        if screen is None:
            return
        column = [screen.data_buffer[y][0].char for y in range(screen.height + 1)]
        if "┌" in column and "└" in column:
            top, bottom = column.index("┌"), column.index("└")
            below = "".join(screen.data_buffer[bottom + 1][x].char for x in range(80))
            seen.append((bottom - top + 1, below))

    session.app.after_render += _measure
    return seen


def test_framed_prompts_stay_compact() -> None:
    reserve = len(SLASH_COMMANDS) + 1
    heights: dict[str, Any] = {}
    with create_pipe_input() as pipe:
        pipe.send_text("/exit\r2\r")
        pipe.close()
        with create_app_session(input=pipe, output=DummyOutput()):
            ui = PromptUI(SLASH_COMMANDS)
            buffer = ui._main.default_buffer
            window = next(w for w in ui._main.layout.find_all_windows() if getattr(w.content, "buffer", None) is buffer)

            def _probe() -> None:  # runs inside the prompt's event loop, before the first render
                heights["closed"] = window.preferred_height(80, 40)
                buffer.complete_state = CompletionState(Document("/"), [Completion("/watch")])
                heights["open"] = window.preferred_height(80, 40)
                buffer.complete_state = None

            main_frames = _frames(ui._main)
            assert ui._main.prompt(pre_run=_probe) == "/exit"
            sub_frames = _frames(ui._sub)
            assert ui.read_sub("select 1-2: ") == "2"
    assert heights["closed"].max == 1  # the input never stretches
    assert heights["open"].preferred == heights["open"].max == reserve  # menu room only while it is open
    assert main_frames and sub_frames
    assert main_frames[0][0] == 3  # one input row inside the frame, not the rows below the cursor
    assert all(height <= reserve + 2 for height, _below in main_frames)
    assert "post-check" in main_frames[0][1]  # the status line sits right under the box
    assert all(height == 3 for height, _below in sub_frames)


def test_activity_indicator_labels() -> None:
    assert phase_label("model", "") == "Thinking"
    assert phase_label("tool", "market.quote") == "Running market.quote"
    assert phase_label("verifying", "") == "Verifying numbers (INV-001)"
    assert phase_label("revising", "") == "Revising the draft (INV-002)"
    assert phase_label("something-else", "x") == "Working"
    readings = iter([100.0, 103.4])
    activity = Activity(lambda: next(readings))
    activity.set_phase("tool", "market.quote")
    shown = rendered_text(activity)
    assert "Running market.quote" in shown and "3s" in shown and "ctrl+c to interrupt" in shown
    screen = Screen(Console(file=io.StringIO(), width=80, color_system=None, force_terminal=False), clock=lambda: 5.0)
    assert screen.activity_label is None
    screen.start_activity()
    assert screen.activity_label == "Thinking"
    screen.set_phase("verifying", "")
    assert screen.activity_label == "Verifying numbers (INV-001)"
    screen.stop_activity()
    assert screen.activity_label is None
