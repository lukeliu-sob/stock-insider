"""TP-021: terminal UI sessions end to end (REQ-SI-FR-026).

The UI runs inside a prompt_toolkit app session fed by pipe input and
writes to a recording Rich console; scripted providers stand in for the
model (the engine is injected through repl._build_engine). The pipe is
closed once the keys are sent, so a prompt that runs out of keys ends
the loop with EOF instead of hanging the suite.

Implements: REQ-SI-FR-026, REQ-SI-FR-013, REQ-SI-FR-019, REQ-SI-FR-023 (ADR-007)
"""

from __future__ import annotations

import io
import json
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console
from typer.testing import CliRunner

from stockinsider.agent import repl as repl_module
from stockinsider.agent.loop import TurnEngine
from stockinsider.agent.profiles import PROFILE_BUDGETS, Profile
from stockinsider.agent.providers import ChatOutcome
from stockinsider.agent.session import SessionStore
from stockinsider.agent.tui import run_tui
from stockinsider.agent.tui.adapter import TuiIO
from stockinsider.agent.tui.fidelity import digit_sequences
from stockinsider.agent.tui.render import Screen
from stockinsider.cli.app import app
from test_streaming import ScriptedProvider

ENTER = "\r"
CTRL_C = "\x03"
CTRL_D = "\x04"
ESC = "\x1b"
DOWN = "\x1b[B"

IDENTITY = """---
version: 1
artifact: identity
---

# Test identity

You are a test analyst.
"""

#: The scripted plain-REPL run behind test/offline/fixtures/plain_repl_golden.txt,
#: captured from the pre-change tree (TP-021).
GOLDEN_SCRIPT = (
    "/sessions\n"
    "/tools\n"
    "/tools budget.query profile=quick\n"
    "/tools nope.tool\n"
    "/bogus\n"
    "/\n"
    "what about 0700.HK?\n"
    "/sync status\n"
    "/watch list\n"
    "/exit\n"
)
GOLDEN = Path(__file__).parent / "fixtures" / "plain_repl_golden.txt"

_SID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")


def normalize(text: str) -> str:
    """Session ids and timestamps vary per run; everything else must not."""
    return _TS.sub("<TS>", _SID.sub("<SID>", text.replace("\r\n", "\n")))


def golden_text() -> str:
    return GOLDEN.read_text(encoding="utf-8").replace("\r\n", "\n")


def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep stores, keys and budgets away from the live worktree and other tests."""
    for var in (
        "PROVIDER_BASE_URL",
        "PROVIDER_CHAT_MODEL",
        "PROVIDER_EMBEDDING_MODEL",
        "PROVIDER_API_KEY",
        "EODHD_API_KEY",
        "STOCKINSIDER_UI",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("STOCKINSIDER_SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(tmp_path / "no-keys.env"))
    for profile, tokens in ((Profile.quick, 30_000), (Profile.standard, 100_000), (Profile.deep, 400_000)):
        monkeypatch.setitem(PROFILE_BUDGETS, profile, tokens)
    return tmp_path


def write_identity(tmp_path: Path) -> Path:
    directory = tmp_path / "prompts"
    directory.mkdir(exist_ok=True)
    (directory / "identity.md").write_text(IDENTITY, encoding="utf-8")
    return directory


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate(tmp_path, monkeypatch)


@pytest.fixture()
def prompts_dir(tmp_path: Path) -> Path:
    return write_identity(tmp_path)


@pytest.fixture()
def store(isolated: Path) -> SessionStore:
    return SessionStore()


def recording_console(width: int = 120) -> Console:
    return Console(file=io.StringIO(), width=width, color_system=None, force_terminal=False, legacy_windows=False)


@contextmanager
def keyboard(keys: str) -> Iterator[None]:
    """Type the keys into a prompt_toolkit app session, then close the input."""
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        pipe.close()
        with create_app_session(input=pipe, output=DummyOutput()):
            yield


def run_ui(
    store: SessionStore,
    keys: str,
    *,
    data_store: Any = None,
    console: Console | None = None,
    width: int = 120,
    clock: Callable[[], float] = time.monotonic,
    resume: bool = False,
    session_id: str | None = None,
) -> str:
    """Run one terminal-UI session on the keys; return what the screen showed."""
    console = console if console is not None else recording_console(width)
    with keyboard(keys):
        run_tui(
            store,
            data_store=data_store,
            console=console,
            clock=clock,
            require_terminal=False,
            resume=resume,
            session_id=session_id,
        )
    return console.file.getvalue()  # type: ignore[attr-defined]


def use_engine(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[ChatOutcome],
    prompts_dir: Path,
    provider: Any = None,
) -> None:
    """Make every session the loop opens use a scripted provider."""
    scripted = provider if provider is not None else ScriptedProvider(outcomes)
    monkeypatch.setattr(
        repl_module,
        "_build_engine",
        lambda store, registry, config: TurnEngine(store, registry, scripted, prompts_dir=prompts_dir),
    )


def tool_call(name: str, arguments: dict) -> dict:
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class FakeClock:
    """Returns the given readings in order, then keeps the last one."""

    def __init__(self, readings: list[float]) -> None:
        self._readings = list(readings)

    def __call__(self) -> float:
        if len(self._readings) > 1:
            return self._readings.pop(0)
        return self._readings[0]


def _plain_session(store: SessionStore, commands: list[str]) -> list[str]:
    lines: list[str] = []
    feed = iter(commands)
    repl_module.start_new_session(store, input_fn=lambda _prompt: next(feed), echo=lines.append)
    return lines


def test_turn_end_to_end(store, prompts_dir, monkeypatch) -> None:
    use_engine(
        monkeypatch,
        [
            ChatOutcome(
                tool_calls=[tool_call("budget.query", {"profile": "standard"})],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            ),
            ChatOutcome(
                text="The standard budget is 100000 tokens.",
                usage={"prompt_tokens": 20, "completion_tokens": 8},
            ),
            # list markers pass the post-check as structure; Markdown would renumber 5 to 2
            ChatOutcome(text="Steps:\n1. Check the quote.\n5. Review the risk.", usage={}),
        ],
        prompts_dir,
    )
    screen = run_ui(store, "what is my budget?" + ENTER + "steps?" + ENTER + "/exit" + ENTER)
    tool_at = screen.index("budget.query … ok (computed)")
    answer_at = screen.index("The standard budget is 100000 tokens.")
    footer_at = screen.index("(tools: 1 · post-check: pass · tokens: 43)")
    assert tool_at < answer_at < footer_at
    session_id = store.list_sessions()[-1]["session_id"]
    recorded = [e["text"] for e in store.read_events(session_id) if e["event"] == "assistant-message"]
    assert recorded == ["The standard budget is 100000 tokens.", "Steps:\n1. Check the quote.\n5. Review the risk."]
    answer_block = screen[tool_at:footer_at].split("\n", 1)[1]
    assert digit_sequences(answer_block) == digit_sequences(recorded[0])
    # render fidelity end to end: the second answer shows as recorded, never renumbered
    second = screen[screen.index("❯ steps?") : screen.index("(tools: 0 · post-check: pass")]
    assert "5. Review the risk." in second
    assert digit_sequences(second.replace("❯ steps?", "")) == digit_sequences(recorded[1])


def test_slash_commands_share_dispatch(store) -> None:
    plain = _plain_session(store, ["/help", "/tools", "/exit"])
    screen = run_ui(store, "/help" + ENTER + "/tools" + ENTER + "/sessions" + ENTER + "/exit" + ENTER, width=500)
    lines = screen.splitlines()
    shared = [line for line in plain if not _SID.search(line)]  # session-specific lines differ per run
    assert any(line.startswith("analysis /report") for line in shared), "the plain /help ran"
    for line in shared:
        assert line in lines, line
    tui_session = store.list_sessions()[-1]
    assert f"{tui_session['session_id']}  {tui_session['created']}  active  -  standard" in lines


def test_ctrl_d_closes_session(store) -> None:
    screen = run_ui(store, CTRL_D)
    row = store.list_sessions()[-1]
    assert row["status"] == "closed"
    assert f"session {row['session_id']} closed" in screen
    assert f"resume with: stockinsider resume {row['session_id']}" in screen


def test_ctrl_c_at_prompt(store) -> None:
    # Ctrl+C with text clears the line; nothing is submitted
    screen = run_ui(store, "hello" + CTRL_C + "/exit" + ENTER)
    assert "❯ hello" not in screen
    assert "provider unconfigured" not in screen
    assert "press ctrl+c again" not in screen  # cleared, not treated as an exit attempt
    assert "❯ /exit" in screen
    # empty prompt: the first press hints, a second within 2 s exits (boundary: 1.9 s)
    screen = run_ui(store, CTRL_C + CTRL_C, clock=FakeClock([10.0, 11.9]))
    assert screen.count("press ctrl+c again to exit") == 1
    assert store.list_sessions()[-1]["status"] == "closed"
    # boundary: 2.1 s later the second press only hints again; a third inside the window exits
    screen = run_ui(store, CTRL_C * 3, clock=FakeClock([10.0, 12.1, 12.5]))
    assert screen.count("press ctrl+c again to exit") == 2
    assert all(row["status"] == "closed" for row in store.list_sessions())


class _InterruptingProvider:
    """Streams a fragment into the engine's buffer, then the user presses Ctrl+C."""

    def complete(self, messages, *, tools=None, stream_sink=None):
        if stream_sink is not None:
            stream_sink("partial words that must never show")
        raise KeyboardInterrupt


def test_ctrl_c_during_turn_interrupts(store, prompts_dir, monkeypatch) -> None:
    use_engine(monkeypatch, [], prompts_dir, provider=_InterruptingProvider())
    created: list[TuiIO] = []
    original = TuiIO.create.__func__  # type: ignore[attr-defined]

    def _recording_create(cls, **kwargs):
        created.append(original(cls, **kwargs))
        return created[-1]

    monkeypatch.setattr(TuiIO, "create", classmethod(_recording_create))
    screen = run_ui(store, "tell me" + ENTER + "/exit" + ENTER)
    assert "turn interrupted" in screen
    assert "partial words" not in screen
    assert "●" not in screen  # no answer block
    assert created[0].screen.activity_label is None  # the indicator did not outlive the turn
    assert "❯ /exit" in screen  # the loop continued
    assert store.list_sessions()[-1]["status"] == "closed"


def test_exception_closes_bound_session(store, monkeypatch) -> None:
    # plain front-end: the first read crashes
    def _crash(_prompt: str) -> str:
        raise RuntimeError("front-end crashed")

    with pytest.raises(RuntimeError, match="front-end crashed"):
        repl_module.start_new_session(store, input_fn=_crash, echo=lambda _line: None)
    earlier = store.list_sessions()[-1]
    assert earlier["status"] == "closed"
    # after a /resume switch, the session bound at the crash is the one closed
    feed = iter([f"/resume {earlier['session_id']}"])

    def _switch_then_crash(_prompt: str) -> str:
        try:
            return next(feed)
        except StopIteration:
            raise RuntimeError("crash after the switch") from None

    with pytest.raises(RuntimeError, match="crash after the switch"):
        repl_module.start_new_session(store, input_fn=_switch_then_crash, echo=lambda _line: None)
    assert [row["status"] for row in store.list_sessions()] == ["closed", "closed"]
    # terminal UI: a rendering failure mid-loop closes the session as well
    original_line = Screen.line

    def _broken_line(self: Screen, text: str) -> None:
        if text.startswith("session  /sessions"):
            raise RuntimeError("render failure")
        original_line(self, text)

    monkeypatch.setattr(Screen, "line", _broken_line)
    with pytest.raises(RuntimeError, match="render failure"):
        run_ui(store, "/help" + ENTER + "/exit" + ENTER)
    assert len(store.list_sessions()) == 3
    assert all(row["status"] == "closed" for row in store.list_sessions())


def test_resume_under_tui(store) -> None:
    _plain_session(store, ["/exit"])
    session_id = store.list_sessions()[-1]["session_id"]
    log = store.root / session_id / "session.jsonl"
    before = log.read_bytes()
    screen = run_ui(store, "/sessions" + ENTER + "/exit" + ENTER, resume=True)
    assert f"session {session_id} resumed (profile: standard; 1 events restored)" in screen
    assert log.read_bytes().startswith(before)  # prior content never rewritten (FR-023)
    assert [row["status"] for row in store.list_sessions()] == ["closed"]


_SGR = re.compile(r"\x1b\[[0-9;]*m")


def test_ui_option_surface(isolated, monkeypatch) -> None:
    runner = CliRunner()
    for args in (["--help"], ["analyze", "--help"], ["resume", "--help"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, args
        # a developer shell may force color (FORCE_COLOR): Rich then styles "-" and "-ui" apart
        assert "--ui" in _SGR.sub("", result.stdout), args
    assert runner.invoke(app, ["--ui", "fancy"], input="/exit\n").exit_code == 2
    monkeypatch.setenv("STOCKINSIDER_UI", "tui")
    result = runner.invoke(app, ["analyze"], input="/exit\n")
    assert result.exit_code == 0
    assert "terminal UI unavailable" in result.stderr  # honored, then explicitly declined
    assert "opened (profile: standard)" in result.stdout
