"""TP-022: slash write commands execute again after H3 (BD-028).

TP-017 PR-2 removed the user_confirmed boolean from every write tool
spec, but the REPL's own /sync, /watch add and /watch remove still sent
it, and the registry rejected them before any data-layer call. These
tests drive the real dispatch and the real registry over a fake data
store that records every call. They also pin the drift class: a literal
tool call in agent/repl.py may only use argument names its tool's spec
declares.

Implements: REQ-SI-FR-001, REQ-SI-FR-004, REQ-SI-FR-013, REQ-SI-INV-004 (ADR-005)
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from stockinsider.agent import repl as repl_module
from stockinsider.agent.repl import build_registry, start_new_session
from stockinsider.agent.session import SessionStore
from test_tui_session import ENTER, isolate, run_ui

SUMMARY = "sync 2026-10-02T00:00:00+00:00: 1 ok, 0 failed, 0 deferred; calls 1/20 (19 remaining)"


class _Candidate:
    def __init__(self, symbol: str, name: str, exchange: str) -> None:
        self._row = {"canonical_symbol": symbol, "official_name": name, "exchange": exchange}

    def as_dict(self) -> dict[str, str]:
        return dict(self._row)


class _Watch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def add_verified(self, symbol: str, *, user_confirmed: bool, via: str) -> dict[str, Any]:
        assert user_confirmed is True  # the data-layer gate still requires the confirmed flag
        self.calls.append(("add", symbol, via))
        return {"status": "active", "canonical_symbol": symbol, "via": via}

    def remove(self, symbol: str) -> dict[str, Any]:
        self.calls.append(("remove", symbol))
        return {"status": "removed", "canonical_symbol": symbol}

    def list(self) -> list[dict[str, str]]:
        return []


class _Resolver:
    def search(self, query: str) -> list[_Candidate]:
        return [_Candidate("0700.HK", "Tencent", "HK")]


class FakeDataStore:
    """Records every data-layer call the slash commands reach."""

    def __init__(self) -> None:
        self.watchlist = _Watch()
        self.resolver = _Resolver()
        self.syncs = 0

    def record(self, candidate: _Candidate) -> None:
        return None

    def run_sync(self, progress: Any = None) -> dict[str, Any]:
        self.syncs += 1
        return {
            "ran_at": "2026-10-02T00:00:00+00:00",
            "counts": {"ok": 1, "failed": 0, "deferred": 0},
            "calls": {"used": 1, "cap": 20, "remaining": 19},
            "results": [],
        }

    def sync_status(self) -> dict[str, Any]:
        return {"budget": {"used": 0, "cap": 20, "remaining": 20}, "active_symbols": 0, "pending_gaps": []}


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate(tmp_path, monkeypatch)


@pytest.fixture()
def store(isolated: Path) -> SessionStore:
    return SessionStore()


def _plain(store: SessionStore, data: FakeDataStore, lines: list[str]) -> list[str]:
    """Run one plain-REPL session on the lines; return everything it echoed."""
    out: list[str] = []
    feed = iter(lines)
    start_new_session(store, data_store=data, input_fn=lambda _prompt: next(feed), echo=out.append)
    return out


def test_slash_sync_runs_after_the_command(store) -> None:
    data = FakeDataStore()
    out = _plain(store, data, ["/sync", "/sync run", "/exit"])
    assert data.syncs == 2
    assert out.count(SUMMARY) == 2
    assert not any("unknown argument" in line for line in out)


@pytest.mark.parametrize("yes", ["y", "Y", " yes "])
def test_slash_watch_add_and_remove_execute_after_yes(store, yes) -> None:
    data = FakeDataStore()
    out = _plain(store, data, ["/watch add tencent", yes, "/watch remove 0700.HK", yes, "/exit"])
    assert data.watchlist.calls == [("add", "0700.HK", "agent-tool"), ("remove", "0700.HK")]
    assert "added 0700.HK; backfill enqueued" in out
    assert "removed 0700.HK" in out


@pytest.mark.parametrize("answer", ["n", "", "q", "ye", "yes please"])
def test_slash_watch_writes_need_a_yes(store, answer) -> None:
    data = FakeDataStore()
    out = _plain(store, data, ["/watch add tencent", answer, "/watch remove 0700.HK", answer, "/exit"])
    assert data.watchlist.calls == []
    assert out.count("cancelled; watchlist unchanged") == 2


def test_unknown_sync_action_still_errors(store) -> None:
    data = FakeDataStore()
    out = _plain(store, data, ["/sync now", "/exit"])
    assert "error: unknown sync action 'now' (run | status)" in out
    assert data.syncs == 0


def test_terminal_ui_slash_writes_execute(store) -> None:
    data = FakeDataStore()
    keys = "/sync" + ENTER + "/watch add tencent" + ENTER + "y" + ENTER + "/exit" + ENTER
    screen = run_ui(store, keys, data_store=data)
    assert data.syncs == 1
    assert data.watchlist.calls == [("add", "0700.HK", "agent-tool")]
    assert SUMMARY in screen
    assert "added 0700.HK; backfill enqueued" in screen
    assert "unknown argument" not in screen


def _literal_tool_calls() -> list[tuple[str, set[str]]]:
    """(tool, argument names) for every ToolCall in agent/repl.py with a literal tool and argument dict."""
    tree = ast.parse(Path(repl_module.__file__).read_text(encoding="utf-8"))
    calls: list[tuple[str, set[str]]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ToolCall"):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        tool, arguments = keywords.get("tool"), keywords.get("arguments")
        if isinstance(tool, ast.Constant) and isinstance(arguments, ast.Dict):
            names = {key.value for key in arguments.keys if isinstance(key, ast.Constant)}
            calls.append((tool.value, names))
    return calls


def test_slash_tool_calls_match_tool_specs(store) -> None:
    specs = {spec.name: spec for spec in build_registry(store, FakeDataStore()).list_tools()}
    calls = _literal_tool_calls()
    assert {"sync.run", "watchlist.add", "watchlist.remove"} <= {tool for tool, _names in calls}
    for tool, names in calls:
        spec = specs[tool]
        declared = set(spec.arguments_spec) | set(spec.optional_spec or {})
        assert names <= declared, f"{tool}: undeclared argument(s) {sorted(names - declared)}"
