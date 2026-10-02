"""TP-023: INV-001 v2 phase 1 - unverified numbers are flagged, not withheld (ADR-008).

Detection is unchanged; the consequence changes. A number the post-check
cannot verify is shown only with the [?] marker and named in a notice;
the record stores the marked text; a number that cannot be marked
withholds the answer (fail-closed). New APIs are reached through the
guardrail module so that, against the pre-change tree, each test fails
on its own instead of the whole module failing to import.

Implements: REQ-SI-INV-001, REQ-SI-FR-008, REQ-SI-QA-004 (ADR-008)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stockinsider.agent import guardrail
from stockinsider.agent.providers import ChatOutcome
from stockinsider.agent.repl import _run_report_turn
from stockinsider.agent.session import SessionError, SessionStore
from test_agent_loop import IDENTITY, Spy, make_engine, tool_call
from test_tui_session import ENTER, isolate, run_ui, use_engine

MARK = "[?]"
NOTICE_999 = "unverified (not found in this session's tool results; marked [?]): 999"
#: "price rises" in Chinese, written as escapes so the repository language gate stays clean
CJK_TEXT = "\u4ef7\u683c\u4e0a\u6da8"
_TOKEN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


@pytest.fixture()
def prompts_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "identity.md").write_text(IDENTITY, encoding="utf-8")
    return directory


@pytest.fixture()
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(root=tmp_path / "sessions")


def _turn(engine, record, text: str = "tell me", profile: str = "standard"):
    spy = Spy()
    outcome = engine.run_turn(
        record["session_id"], text, profile=profile,
        render=spy.render, progress=spy.progress, stream_sink=spy.sink,
    )
    return outcome, spy


def _assistant_events(store: SessionStore, record) -> list[dict]:
    return [e for e in store.read_events(record["session_id"]) if e["event"] == "assistant-message"]


def test_unverified_number_is_marked_not_withheld(store, prompts_dir) -> None:
    engine = make_engine(store, [ChatOutcome(text="The answer is 999.", usage={})], prompts_dir)
    record = store.create(profile="standard")
    outcome, spy = _turn(engine, record)
    assert outcome.quarantined is False
    assert outcome.unverified == ["999"]
    assert outcome.displayed == "The answer is 999[?]."
    # the answer channel carries the MARKED text once; the raw deltas are never replayed
    assert spy.streamed == ["The answer is 999[?].", "\n"]
    assert NOTICE_999 in spy.lines
    assert any("post-check: flagged" in line for line in spy.lines)
    event = _assistant_events(store, record)[-1]
    assert event["text"] == "The answer is 999[?]."
    assert event["post_check"] == "flagged"
    assert event["unverified"] == ["999"]
    assert event["original"] == "The answer is 999."
    assert not [e for e in store.read_events(record["session_id"]) if e["event"] == "error"]


LEDGER = {"turn-0001/market.quote#1": {"symbol": "1211.HK", "close": 75.6, "volume": 18982584}}
BATTERY = [
    "The answer is 999 and again 999.",
    "| Field | Value |\n|---|---|\n| Close | 75.6 |\n| Target | 120.5 |",
    "Volatility is about 37%, high.",
    "Published 20260929T123202178Z, polarity 0.998.",
    "The **0.37** figure and (42%) both.",
    "Drawdown -0.36 versus a close of 75.6.",
    "Turnover was 1,234,567 shares.",
    "First line 555\nSecond line 555 again.",
    "Printed at 12:32:02 UTC.",
    "999 opens the text.",
    "The text ends with 999",
]


def _words(text: str) -> list[str]:
    return [word for word in re.split(r"[\s|]+", text) if word]


@pytest.mark.parametrize("text", BATTERY)
def test_every_unverified_occurrence_is_marked(text) -> None:
    verdict = guardrail.run_postcheck(text, LEDGER)
    assert verdict.flagged is True and verdict.quarantined is False
    shown = verdict.display_text
    assert shown.replace(MARK, "") == text  # the marker only adds, never alters
    unverified = set(verdict.unverified)
    assert unverified
    for word in _words(shown):
        tokens = {t.replace(",", "") for t in _TOKEN.findall(word.replace(MARK, ""))}
        if tokens & unverified:
            assert MARK in word, f"unmarked unverified number in {word!r} ({text!r})"
        elif MARK in word:
            pytest.fail(f"marker on a word without an unverified number: {word!r}")


def test_verified_number_in_battery_stays_unmarked() -> None:
    verdict = guardrail.run_postcheck("| Close | 75.6 |\n| Target | 120.5 |", LEDGER)
    assert "| 75.6 |" in verdict.display_text
    assert "120.5[?]" in verdict.display_text


def test_unmarkable_number_withholds(store, prompts_dir) -> None:
    ledger = {"turn-0001/market.quote#1": {"date": "2026-09-30", "close": 75.6}}
    verdict = guardrail.run_postcheck("The close on 2026-09-28 was 75.6.", ledger)
    assert verdict.quarantined is True and verdict.flagged is False
    assert verdict.display_text == "data unavailable for: 20260928"
    # end to end: withheld exactly as before, nothing streamed
    engine = make_engine(store, [ChatOutcome(text="The answer is 2026-09-28.", usage={})], prompts_dir)
    record = store.create(profile="standard")
    outcome, spy = _turn(engine, record)
    assert outcome.quarantined is True
    assert outcome.displayed.startswith("data unavailable for:")
    assert spy.streamed == []
    assert _assistant_events(store, record)[-1]["post_check"] == "failed"


def test_verified_answers_are_unchanged(store, prompts_dir) -> None:
    engine = make_engine(
        store,
        [
            ChatOutcome(tool_calls=[tool_call("budget.query", {"profile": "quick"})], usage={}),
            ChatOutcome(text="The quick budget is 30000 tokens.", usage={}),
        ],
        prompts_dir,
    )
    record = store.create(profile="quick")
    outcome, spy = _turn(engine, record, "budget?", profile="quick")
    assert outcome.unverified == []
    assert "".join(spy.streamed) == "The quick budget is 30000 tokens. \n\n"  # deltas replayed as before
    assert not any(MARK in piece for piece in spy.streamed)
    assert not any(line.startswith("unverified") for line in spy.lines)
    assert any("post-check: pass" in line for line in spy.lines)
    assert _assistant_events(store, record)[-1]["post_check"] == "ok"


def test_history_names_unverified_numbers(store, prompts_dir) -> None:
    engine = make_engine(
        store,
        [ChatOutcome(text="The answer is 999.", usage={}), ChatOutcome(text="As I said, 999.", usage={})],
        prompts_dir,
    )
    record = store.create(profile="standard")
    _turn(engine, record)
    second, _spy = _turn(engine, record, "and again?")
    sent = engine._provider.seen_messages[-1]  # noqa: SLF001 - the request the model received
    assistant = [m["content"] for m in sent if m.get("role") == "assistant"]
    assert assistant == [
        "The answer is 999[?].\n[harness] The numbers marked [?] were not verified against "
        "tool results: 999; do not restate them as facts."
    ]
    assert second.unverified == ["999"]  # restating it later does not verify it (no laundering)


def test_report_stored_with_markers(store, prompts_dir) -> None:
    flagged = make_engine(store, [ChatOutcome(text="BYD report: target 999.", usage={})], prompts_dir)
    record = store.create(profile="standard")
    lines: list[str] = []
    _run_report_turn(flagged, store, record, "1211.HK", lines.append)
    stored = sorted((store.root / record["session_id"] / "artifacts").glob("report-*.md"))
    assert len(stored) == 1
    content = stored[0].read_text(encoding="utf-8")
    assert "BYD report: target 999[?]." in content
    assert "- unverified numbers: 1 (marked [?]; not verified by the INV-001 post-check)" in content
    assert "passed the INV-001 post-check" not in content
    assert any(line.startswith("report stored:") and "1 unverified number" in line for line in lines)
    # a fully verified report keeps the "passed" line
    verified = make_engine(
        store,
        [
            ChatOutcome(tool_calls=[tool_call("budget.query", {"profile": "quick"})], usage={}),
            ChatOutcome(text="The quick budget is 30000 tokens.", usage={}),
        ],
        prompts_dir,
    )
    record2 = store.create(profile="standard")
    _run_report_turn(verified, store, record2, "1211.HK", lambda _line: None)
    content2 = next((store.root / record2["session_id"] / "artifacts").glob("report-*.md")).read_text(encoding="utf-8")
    assert "passed the INV-001 post-check" in content2 and "unverified numbers" not in content2
    # a withheld answer (language policy) stores nothing
    withheld = make_engine(store, [ChatOutcome(text=CJK_TEXT, usage={})], prompts_dir)
    record3 = store.create(profile="standard")
    lines3: list[str] = []
    _run_report_turn(withheld, store, record3, "1211.HK", lines3.append)
    assert not list((store.root / record3["session_id"] / "artifacts").glob("report-*.md"))
    assert any(line.startswith("report not stored") for line in lines3)


STREAK = "three answers in a row contained unverified numbers; check the data (/sync status) or start a new session"


def test_streak_notice_replaces_numeric_abort(store, prompts_dir) -> None:
    answers = [ChatOutcome(text=f"The answer is {900 + i}.", usage={}) for i in range(3)]
    engine = make_engine(store, answers, prompts_dir)
    record = store.create(profile="standard")
    outcomes = [_turn(engine, record, f"q{i}") for i in range(3)]
    assert [STREAK in spy.lines for _outcome, spy in outcomes] == [False, False, True]
    assert all(outcome.aborted is None for outcome, _spy in outcomes)
    row = next(r for r in store.list_sessions() if r["session_id"] == record["session_id"])
    assert row["status"] == "active"
    # boundary: a verified answer in between resets the streak
    engine2 = make_engine(
        store,
        [
            ChatOutcome(text="The answer is 901.", usage={}),
            ChatOutcome(text="The answer is 902.", usage={}),
            ChatOutcome(text="No numbers this time.", usage={}),
            ChatOutcome(text="The answer is 903.", usage={}),
        ],
        prompts_dir,
    )
    record2 = store.create(profile="standard")
    spies = [_turn(engine2, record2, f"q{i}")[1] for i in range(4)]
    assert not any(STREAK in spy.lines for spy in spies)


def test_streak_follows_the_answer_as_shown(store, prompts_dir) -> None:
    # a regenerated answer counts by its own recheck, not by the draft it replaced
    counts = make_engine(
        store,
        [
            ChatOutcome(text="The answer is 901.", usage={}),
            ChatOutcome(text="BYD will surge.", usage={}),
            ChatOutcome(text="Hypothesis: BYD might reach 902.", usage={}),
            ChatOutcome(text="The answer is 903.", usage={}),
        ],
        prompts_dir,
    )
    record = store.create(profile="standard")
    spies = [_turn(counts, record, f"q{i}")[1] for i in range(3)]
    assert [STREAK in spy.lines for spy in spies] == [False, False, True]
    # and a draft's unverified number that never reached the screen does not count
    resets = make_engine(
        store,
        [
            ChatOutcome(text="The answer is 901.", usage={}),
            ChatOutcome(text="BYD will surge to 902.", usage={}),
            ChatOutcome(text="Hypothesis: BYD might rise.", usage={}),
            ChatOutcome(text="The answer is 903.", usage={}),
        ],
        prompts_dir,
    )
    record2 = store.create(profile="standard")
    spies2 = [_turn(resets, record2, f"q{i}")[1] for i in range(3)]
    assert not any(STREAK in spy.lines for spy in spies2)


def test_epistemic_abort_still_trips(store, prompts_dir) -> None:
    outcomes = []
    for _ in range(3):
        outcomes += [
            ChatOutcome(text="BYD will surge.", usage={}),
            ChatOutcome(text="Hypothesis: BYD might rise.", usage={}),
        ]
    engine = make_engine(store, outcomes, prompts_dir)
    record = store.create(profile="standard")
    results = [_turn(engine, record, f"q{i}")[0] for i in range(3)]
    assert results[-1].aborted == "abort:epistemic"
    row = next(r for r in store.list_sessions() if r["session_id"] == record["session_id"])
    assert row["status"] == "aborted"
    with pytest.raises(SessionError, match="aborted"):
        store.resume(record["session_id"])


def test_language_policy_still_withholds() -> None:
    verdict = guardrail.run_postcheck(CJK_TEXT + " 999", {})
    assert verdict.quarantined is True and verdict.flagged is False
    assert verdict.display_text == "response withheld: language policy violation (GOV-001)"


def test_epistemic_regeneration_then_marking(store, prompts_dir) -> None:
    engine = make_engine(
        store,
        [
            ChatOutcome(text="It will surge to 999.", usage={}),
            ChatOutcome(text="Hypothesis: it might reach 999.", usage={}),
        ],
        prompts_dir,
    )
    record = store.create(profile="standard")
    outcome, spy = _turn(engine, record)
    assert outcome.displayed == "Hypothesis: it might reach 999[?]."
    assert outcome.unverified == ["999"]
    shown = "".join(spy.streamed) + "\n".join(spy.lines)
    assert shown.count("Hypothesis: it might reach 999[?].") == 1
    assert "will surge" not in shown
    event = _assistant_events(store, record)[-1]
    assert event["post_check"] == "flagged" and event["text"] == "Hypothesis: it might reach 999[?]."


def test_tui_shows_markers_and_notice(tmp_path, monkeypatch, prompts_dir) -> None:
    isolate(tmp_path, monkeypatch)
    tui_store = SessionStore()
    use_engine(monkeypatch, [ChatOutcome(text="The answer is 999.", usage={})], prompts_dir)
    screen = run_ui(tui_store, "tell me" + ENTER + "/exit" + ENTER)
    assert "The answer is 999[?]." in screen  # Markdown keeps the marker literal
    assert NOTICE_999 in screen
    assert "data unavailable" not in screen
