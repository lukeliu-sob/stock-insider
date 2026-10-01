"""TP-021: terminal UI invariant suite - display (INV-001), consent (INV-004), fallbacks (INV-003).

Adversarial and negative cases: what the screen must never show, which
keys must never execute a write, and how an unusable terminal fails
explicitly. Harness helpers are shared with test_tui_session.

Implements: REQ-SI-FR-026, REQ-SI-INV-001, REQ-SI-INV-003, REQ-SI-INV-004 (ADR-007)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from stockinsider.agent import tui as tui_package
from stockinsider.agent.providers import ChatOutcome
from stockinsider.agent.session import SessionStore
from stockinsider.agent.tui import TuiDependencyMissing, TuiUnavailable, run_tui
from stockinsider.agent.tui import prompt as prompt_module
from stockinsider.agent.tui.adapter import TuiIO
from stockinsider.agent.tui.render import Screen
from stockinsider.cli.app import app
from test_streaming import ScriptedProvider
from test_tui_session import (
    CTRL_C,
    DOWN,
    ENTER,
    ESC,
    GOLDEN_SCRIPT,
    golden_text,
    isolate,
    keyboard,
    normalize,
    recording_console,
    run_ui,
    tool_call,
    use_engine,
    write_identity,
)


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate(tmp_path, monkeypatch)


@pytest.fixture()
def prompts_dir(tmp_path: Path) -> Path:
    return write_identity(tmp_path)


@pytest.fixture()
def store(isolated: Path) -> SessionStore:
    return SessionStore()


# -- fakes for the write path -------------------------------------------------


class _Candidate:
    def __init__(self, symbol: str, name: str, exchange: str) -> None:
        self.canonical_symbol = symbol
        self.official_name = name
        self.exchange = exchange

    def as_dict(self) -> dict[str, str]:
        return {
            "canonical_symbol": self.canonical_symbol,
            "official_name": self.official_name,
            "exchange": self.exchange,
        }


class _Watch:
    def __init__(self) -> None:
        self.added: list[tuple[str, str]] = []

    def add_verified(self, symbol: str, *, user_confirmed: bool, via: str) -> dict[str, Any]:
        assert user_confirmed is True
        self.added.append((symbol, via))
        return {"status": "active", "canonical_symbol": symbol, "via": via}

    def remove(self, symbol: str) -> dict[str, Any]:
        return {"status": "removed", "canonical_symbol": symbol}

    def list(self) -> list[dict[str, str]]:
        return [{"canonical_symbol": s, "official_name": s, "exchange": "HK"} for s, _via in self.added]


class _Resolver:
    def __init__(self, candidates: list[_Candidate]) -> None:
        self._candidates = candidates

    def search(self, query: str) -> list[_Candidate]:
        return list(self._candidates)


class FakeDataStore:
    def __init__(self, candidates: list[_Candidate] | None = None) -> None:
        self.watchlist = _Watch()
        self.resolver = _Resolver(candidates or [])

    def record(self, candidate: _Candidate) -> None:
        return None

    def run_sync(self, progress: Any = None) -> dict[str, Any]:
        return {"counts": {"ok": 0, "failed": 0, "deferred": 0}}

    def sync_status(self) -> dict[str, Any]:
        return {"budget": {"remaining": 5}, "active_symbols": 0, "pending_gaps": []}


def _propose_add() -> list[ChatOutcome]:
    return [
        ChatOutcome(tool_calls=[tool_call("watchlist.add", {"canonical_symbol": "0700.HK"})], usage={}),
        ChatOutcome(text="Please confirm the watchlist addition in the terminal.", usage={}),
    ]


# -- INV-001: the screen shows only verified model text -----------------------


class _WatchingProvider(ScriptedProvider):
    """Captures the screen at every delta the model streams."""

    def __init__(self, outcomes: list[ChatOutcome], console: Any) -> None:
        super().__init__(outcomes)
        self.console = console
        self.screens: list[str] = []

    def complete(self, messages, *, tools=None, stream_sink=None):
        if stream_sink is None:
            return super().complete(messages, tools=tools, stream_sink=None)

        def _spy(piece: str) -> None:
            stream_sink(piece)
            self.screens.append(self.console.file.getvalue())

        return super().complete(messages, tools=tools, stream_sink=_spy)


def test_no_model_text_before_verdict(store, prompts_dir, monkeypatch) -> None:
    console = recording_console()
    provider = _WatchingProvider(
        [
            ChatOutcome(tool_calls=[tool_call("budget.query", {"profile": "standard"})], usage={}),
            ChatOutcome(text="The standard budget is 100000 tokens.", usage={}),
        ],
        console,
    )
    use_engine(monkeypatch, [], prompts_dir, provider=provider)
    run_ui(store, "what is my budget?" + ENTER + "/exit" + ENTER, console=console)
    assert provider.screens, "the model streamed"
    for screen in provider.screens:
        assert "standard budget is" not in screen  # nothing shows while the model streams
    assert "The standard budget is 100000 tokens." in console.file.getvalue()  # shown after the verdict


def test_quarantined_original_never_displayed(store, prompts_dir, monkeypatch) -> None:
    use_engine(monkeypatch, [ChatOutcome(text="The answer is 999.", usage={})], prompts_dir)
    screen = run_ui(store, "tell me" + ENTER + "/exit" + ENTER)
    assert "answer is" not in screen
    assert "data unavailable for: 999" in screen
    assert "●" not in screen  # the degraded line is a notice, not an answer


def test_regenerated_answer_displayed_once(store, prompts_dir, monkeypatch) -> None:
    use_engine(
        monkeypatch,
        [
            ChatOutcome(text="It will surge.", usage={}),
            ChatOutcome(text="It might rise (hypothesis).", usage={}),
        ],
        prompts_dir,
    )
    screen = run_ui(store, "outlook?" + ENTER + "/exit" + ENTER)
    assert "will surge" not in screen
    assert screen.count("It might rise (hypothesis).") == 1


# -- INV-004: a proposed write needs an explicit accept -----------------------


def test_write_confirmation_defaults_to_decline(store, prompts_dir, monkeypatch) -> None:
    data = FakeDataStore()
    use_engine(monkeypatch, _propose_add(), prompts_dir)
    screen = run_ui(store, "add tencent" + ENTER + ENTER + "/exit" + ENTER, data_store=data)
    assert data.watchlist.added == []
    assert 'declined: watchlist.add {"canonical_symbol": "0700.HK"} was not executed' in screen
    assert "confirmed:" not in screen


def test_write_confirmation_escape_and_ctrl_c_decline(store, prompts_dir, monkeypatch) -> None:
    for key in (ESC, CTRL_C):
        data = FakeDataStore()
        use_engine(monkeypatch, _propose_add(), prompts_dir)
        screen = run_ui(store, "add tencent" + ENTER + key + "/exit" + ENTER, data_store=data)
        assert data.watchlist.added == [], repr(key)
        assert "declined: watchlist.add" in screen, repr(key)


def test_write_confirmation_no_single_keystroke_accept(store, prompts_dir, monkeypatch) -> None:
    for keys in ("1", "2", "y", " ", "j", "yes please, add it"):
        data = FakeDataStore()
        use_engine(monkeypatch, _propose_add(), prompts_dir)
        run_ui(store, "add tencent" + ENTER + keys + ENTER + "/exit" + ENTER, data_store=data)
        assert data.watchlist.added == [], repr(keys)


def test_write_confirmation_accept_executes_once(store, prompts_dir, monkeypatch) -> None:
    monkeypatch.setattr("stockinsider.agent.confirm.secrets.choice", lambda alphabet: "a")
    data = FakeDataStore()
    use_engine(monkeypatch, _propose_add(), prompts_dir)
    screen = run_ui(
        store,
        "add tencent" + ENTER + DOWN + ENTER + "confirm aaaaaaaa" + ENTER + "/exit" + ENTER,
        data_store=data,
    )
    assert data.watchlist.added == [("0700.HK", "agent-tool")]
    assert 'confirmed: watchlist.add {"canonical_symbol": "0700.HK"} executed (single-use token consumed)' in screen
    assert "unknown or already-used token; nothing executed (INV-004)" in screen  # the replay


class _StubPrompt:
    def __init__(self, lines: list[str]) -> None:
        self.lines = list(lines)
        self.confirmations: list[str] = []

    def read_main(self, status: Any) -> str:
        return self.lines.pop(0)

    def read_sub(self, message: str) -> str:
        return "q"

    def confirm_write(self, tool: str, arguments: Any) -> bool:
        self.confirmations.append(tool)
        return True


def test_pending_confirmations_dropped_on_session_switch() -> None:
    stub = _StubPrompt(["/exit", "/exit"])
    tui = TuiIO(stub, Screen(recording_console()))  # type: ignore[arg-type]
    tui.status(lambda: {"session_id": "session-a"})
    tui.pending_write("abcdefgh", "watchlist.add", {"canonical_symbol": "0700.HK"})
    tui.status(lambda: {"session_id": "session-b"})  # /resume switched the binding
    assert tui.ask("> ", main=True) == "/exit"
    assert stub.confirmations == []
    # within one session the proposal is asked about before the next prompt
    tui.pending_write("bcdefghi", "watchlist.add", {"canonical_symbol": "0700.HK"})
    tui.status(lambda: {"session_id": "session-b"})
    assert tui.ask("> ", main=True) == "confirm bcdefghi"
    assert stub.confirmations == ["watchlist.add"]


def test_sub_prompt_cancel_is_safe(store) -> None:
    two = [_Candidate("0700.HK", "Tencent", "HK"), _Candidate("TCEHY.US", "Tencent ADR", "US")]
    data = FakeDataStore(two)
    screen = run_ui(store, "/watch add tencent" + ENTER + CTRL_C + "/exit" + ENTER, data_store=data)
    assert "error: invalid selection; cancelled" in screen
    assert data.watchlist.added == []
    data = FakeDataStore(two[:1])
    screen = run_ui(store, "/watch add tencent" + ENTER + ESC + "/exit" + ENTER, data_store=data)
    assert "cancelled; watchlist unchanged" in screen
    assert data.watchlist.added == []
    # the /resume picker: a cancel never resumes entry 1 (Enter would)
    screen = run_ui(store, "/resume" + ENTER + CTRL_C + "/exit" + ENTER)
    assert "resume cancelled" in screen
    assert "resumed (" not in screen


# -- FR-013 / INV-003: plain stays plain, fallbacks are explicit -----------------


def test_plain_output_byte_identical(isolated) -> None:
    result = CliRunner().invoke(app, [], input=GOLDEN_SCRIPT)
    assert result.exit_code == 0
    assert normalize(result.stdout) == golden_text()


class _Stream:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class _Sys:
    def __init__(self, stdin_tty: bool, stdout_tty: bool) -> None:
        self.stdin = _Stream(stdin_tty)
        self.stdout = _Stream(stdout_tty)


def test_tui_without_terminal_falls_back_explicitly(isolated, monkeypatch) -> None:
    result = CliRunner().invoke(app, ["--ui", "tui"], input=GOLDEN_SCRIPT)
    assert result.exit_code == 0
    assert (
        "note: terminal UI unavailable (stdin and stdout must both be an interactive terminal); "
        "using the plain REPL"
    ) in result.stderr
    assert normalize(result.stdout) == golden_text()
    # boundary: the UI starts only when BOTH streams are terminals
    store = SessionStore()
    for stdin_tty, stdout_tty in ((True, False), (False, True), (False, False)):
        monkeypatch.setattr(tui_package, "sys", _Sys(stdin_tty, stdout_tty))
        with pytest.raises(TuiUnavailable, match="interactive terminal"):
            run_tui(store, console=recording_console())
    assert len(store.list_sessions()) == 1  # only the plain run above opened one
    monkeypatch.setattr(tui_package, "sys", _Sys(True, True))
    console = recording_console()
    with keyboard("/exit" + ENTER):
        run_tui(store, console=console)
    assert "Stock Insider" in console.file.getvalue()  # the UI ran: welcome panel shown
    assert len(store.list_sessions()) == 2


def test_console_unavailable_falls_back_explicitly(isolated, monkeypatch) -> None:
    def _no_console(self: Any, commands: Any) -> None:
        raise RuntimeError("NoConsoleScreenBufferError: not a Windows console")

    monkeypatch.setattr(prompt_module.PromptUI, "__init__", _no_console)
    store = SessionStore()
    with pytest.raises(TuiUnavailable, match="console unavailable"):
        run_tui(store, console=recording_console(), require_terminal=False)
    assert store.list_sessions() == []  # checked before any session opened

    def _unavailable(*args: Any, **kwargs: Any) -> None:
        raise TuiUnavailable("console unavailable: RuntimeError: not a Windows console")

    monkeypatch.setattr("stockinsider.agent.tui.run_tui", _unavailable)
    result = CliRunner().invoke(app, ["--ui", "tui"], input="/exit\n")
    assert result.exit_code == 0
    assert "terminal UI unavailable (console unavailable" in result.stderr
    assert len(store.list_sessions()) == 1  # the plain REPL opened exactly one


def test_missing_dependency_is_explicit(isolated, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "prompt_toolkit", None)
    store = SessionStore()
    with pytest.raises(TuiDependencyMissing, match="prompt_toolkit"):
        run_tui(store, require_terminal=False)
    result = CliRunner().invoke(app, ["--ui", "tui"], input="/exit\n")
    assert result.exit_code == 2
    assert "prompt_toolkit" in result.stderr and "--ui plain" in result.stderr
    assert store.list_sessions() == []
