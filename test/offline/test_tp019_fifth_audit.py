"""TP-019 adversarial suite: fifth-audit remediation.

One negative/adversarial test (at least) per fifth-report finding
(docs/test-plans/TP-019.md): letter-glued numerics and identifier
whitelist (F1), loopback-by-address egress (F2), the regeneration
request and its record (F3), the message-based history window (F4),
narrowed attribution and clause-local hedges (F5), sync empty-fetch
honesty (F6), daily benchmark refresh and cursor-bounded detection
(F7), script-based language policy (F8), the remaining static-gate
idioms (F9), the low items (vol alias, prelude separator, report
body, no-data visibility), and the AI-use log structure check (BD-025).

Implements: REQ-SI-INV-001, REQ-SI-INV-002, REQ-SI-INV-003,
REQ-SI-SEC-003, REQ-SI-FR-001, REQ-SI-FR-006, REQ-SI-FR-008,
REQ-SI-FR-011, REQ-SI-FR-014, REQ-SI-FR-019, REQ-SI-GOV-001
(ADR-001 Am1, ADR-002 Am1, ADR-004 Am4, ADR-006 Am8; TP-019)
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from stockinsider.agent.guardrail import epistemic_filter, postcheck_numbers
from stockinsider.shared.egress import EgressViolationError, validate_egress_url
from stockinsider.shared.language import first_violation, is_english_only

QUOTE_POOL = {
    "turn-0001/market.quote#1": {
        "date": "2026-09-26",
        "open": 629.0,
        "high": 634.0,
        "low": 627.0,
        "close": 630.5,
        "volume": 20000029,
        "adjusted_close": 630.5,
        "symbol": "0700.HK",
    }
}
NEWS_POOL = {
    "turn-0001/news.recent#1": {
        "items": [{"seendate": "20260923T183300Z", "title": "Tencent expands cloud AI"}]
    }
}


# ---- F1: INV-001 letter-glued numerics / identifier whitelist -------------------


def test_letter_glued_numerics_are_checked() -> None:
    """TP-018b blanked any short letter run glued to digits: these escaped."""
    cases = {
        "Tencent closed at HKD777.": "777",
        "Price target: USD1200.": "1200",
        "Tencent trades at PE35 versus peers.": "35",
        "Revenue hit RMB500 billion.": "500",
        "YTD-12% for the stock.": "-12",
    }
    for text, token in cases.items():
        check = postcheck_numbers(text, QUOTE_POOL)
        assert not check.passed, text
        assert token in check.failed, (text, check.failed)


def test_governance_identifiers_still_not_numerics() -> None:
    for text in (
        "Per ADR-005 Am2 and GOV-001, see TP-019, BD-020, RM-56, PR-2 and INV-001.",
        "REQ-SI-FR-006 and SEC-003 govern this; AILOG-0065 records it.",
        "Q3 results and H1 guidance for FY2026 (identity-v6).",
        "The S&P 500 and the Nasdaq-100 are benchmarks.",
    ):
        assert postcheck_numbers(text, {}).failed == [], text


def test_identifier_whitelist_boundary() -> None:
    assert postcheck_numbers("Q4 results are due.", {}).failed == []
    assert postcheck_numbers("Q5 results are due.", {}).failed == ["5"]


def test_currency_glued_pool_value_passes() -> None:
    assert postcheck_numbers("0700.HK closed at HKD630.5 on 2026-09-26.", QUOTE_POOL).passed


def test_natural_dates_fold_to_pool_dates() -> None:
    assert postcheck_numbers("The article appeared on September 23, 2026.", NEWS_POOL).passed
    assert postcheck_numbers("Seen on 23 Sep 2026.", NEWS_POOL).passed
    # a natural date that is NOT in the evidence still fails
    absent = postcheck_numbers("It appeared on September 24, 2026.", NEWS_POOL)
    assert absent.failed == ["September 24, 2026"]  # TP-024 (ADR-008 Am1): the date as written


def test_vol_abbreviation_is_not_volume() -> None:
    # "vol" abbreviates volatility; mapping it to volume mis-typed the high
    check = postcheck_numbers("Realized vol is elevated; the session peaked at 634.", QUOTE_POOL)
    assert check.passed, check.field_mismatch
    # the real field word still types the value
    assert postcheck_numbers("Volume was 634.", QUOTE_POOL).field_mismatch == ["634"]


# ---- F5: INV-002 attribution adjacency, clause-local hedges -----------------------


def test_inference_verb_attribution_does_not_launder() -> None:
    for sentence in (
        "The chart suggests the company will rise 20% next quarter.",
        "Momentum indicates the company's shares will double this year.",
        "Our analysis suggests the stock will rise; the company is strong.",
        "The report suggests shares will rise next month.",
        "According to the report, the stock will rise next month.",
        "The RSI confirmed the exchange rally will continue.",
        "The trend indicates the stock will surge, as the statement shows.",
        "Price action noted that the stock will climb after the release.",
        "Management said revenue grew, but the stock will fall next month.",
    ):
        assert epistemic_filter(sentence).violations, sentence


def test_institutional_speech_acts_still_exempt() -> None:
    for sentence in (
        "Management said it will increase the dividend.",
        "The company announced that revenue will decline.",
        "The CEO said the company will increase the buyback.",
        "According to the filing, shares will be delisted.",
        "Guidance indicates the price will recover, the filing states.",
        "The stock will rise after the listing, the company has said.",
    ):
        assert epistemic_filter(sentence).passed, sentence


def test_hedge_is_clause_local() -> None:
    for sentence in (
        "Revenue may dip, but the stock will double next year.",
        "Margins could improve; either way the shares will rise 20% by December.",
    ):
        assert epistemic_filter(sentence).violations, sentence
    # a hedge inside the claim's own clause still labels it
    assert epistemic_filter("Shares could double if margins recover.").passed


def test_month_may_is_not_a_hedge() -> None:
    assert epistemic_filter("In May the stock will rise.").violations
    assert epistemic_filter("Hypothesis: the stock will rise in May.").passed


def test_recall_batch_classes_caught() -> None:
    for sentence in (
        "The stock will likely rise next month.",
        "Shares fell 5% due to the earnings miss.",
        "The stock dropped because investors fear regulation.",
        "Strong buybacks drove the share price higher.",
        "The sell-off was caused by the regulatory news.",
        "Alibaba will outperform the index this quarter.",
        "Tencent should hit 700 before Christmas.",
        "The stock is headed for 800.",
        "Expect a rebound next week.",
    ):
        assert epistemic_filter(sentence).violations, sentence
    for sentence in (
        "The close fell 1.2% on the day.",
        "Shares fell after the earnings release.",
        "The index is due to be rebalanced next week.",
    ):
        assert epistemic_filter(sentence).passed, sentence


# ---- F2: SEC-003 loopback is an address --------------------------------------------


def test_loopback_is_an_address_not_a_prefix() -> None:
    for url in (
        "http://127.attacker.example/v1",
        "https://127.0.0.1.nip.io/v1",
        "http://127.1.2.3.evil.example/exfil",
    ):
        with pytest.raises(EgressViolationError):
            validate_egress_url(url)


def test_loopback_boundary() -> None:
    for url in (
        "http://127.0.0.1:8000/v1",
        "http://127.255.255.254/v1",
        "http://[::1]:8080/v1",
        "http://localhost:11434/v1",
    ):
        validate_egress_url(url)
    with pytest.raises(EgressViolationError):
        validate_egress_url("http://128.0.0.1/v1")


# ---- F8: language policy by script --------------------------------------------------


def test_symbols_and_emoji_are_not_language() -> None:
    for text in (
        "Check: " + chr(0x2713) + " data complete, " + chr(0x2714) + " verified",
        chr(0x25B2) + " +2.1% / " + chr(0x25BC) + " -0.4% " + chr(0x25BA) + " key point",
        chr(0x1F4A1) + " Insight " + chr(0x1F50D) + " Details " + chr(0x2B50) + " " + chr(0x2605),
        chr(0x1F7E2) + " up " + chr(0x1F534) + " down",
        "12" + chr(0x2009) + "% (thin space), " + chr(0x2153) + " of the float",
        "Nguy" + chr(0x1EC5) + "n (Latin Extended Additional)",
    ):
        assert is_english_only(text), (text, first_violation(text))


def test_greek_math_letters_only() -> None:
    for text in ("Volatility " + chr(0x3C3) + " = 18.57%", "Beta " + chr(0x3B2) + " = 1.2", chr(0x394) + " price"):
        assert is_english_only(text), text
    greek_word = chr(0x3A4) + chr(0x3B9) + chr(0x3BC) + chr(0x3AE)
    assert not is_english_only("Price " + greek_word)


def test_foreign_scripts_digits_and_controls_fail_closed() -> None:
    for text in (
        chr(0x645) + chr(0x631) + chr(0x62D) + chr(0x628) + chr(0x627),  # Arabic
        chr(0x5E9) + chr(0x5DC) + chr(0x5D5) + chr(0x5DD),  # Hebrew
        chr(0x928) + chr(0x92E) + chr(0x938) + chr(0x94D) + chr(0x924) + chr(0x947),  # Devanagari
        chr(0xE2A) + chr(0xE27) + chr(0xE31) + chr(0xE2A),  # Thai
        "price " + chr(0x663) + chr(0x660) + chr(0x660),  # Arabic-Indic digits
        "abc" + chr(0x202E) + "def",  # bidi override
        "Hello" + chr(0xFF01),  # fullwidth punctuation
        "note" + chr(0x3002),  # CJK punctuation
        "x" + chr(0x7) + "y",  # control character
    ):
        assert not is_english_only(text), repr(text)


# ---- F3 / F4 / F10: agent loop ------------------------------------------------------


IDENTITY = "---\nversion: 1\nartifact: identity\n---\n\n# Test identity\n\nYou are a test analyst.\n"


@pytest.fixture()
def prompts_dir(tmp_path) -> Path:
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "identity.md").write_text(IDENTITY, encoding="utf-8")
    return directory


@pytest.fixture()
def session_store(tmp_path):
    from stockinsider.agent.session import SessionStore

    return SessionStore(root=tmp_path / "sessions")


class _Provider:
    """Scripted provider that also streams text emitted WITH tool calls (preludes)."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.seen_messages: list[list[dict]] = []
        self.seen_tools: list = []

    def complete(self, messages, *, tools=None, stream_sink=None):
        """Implements: REQ-SI-FR-019 (ADR-001)."""
        self.seen_messages.append([dict(m) for m in messages])
        self.seen_tools.append(tools)
        outcome = self._outcomes.pop(0)
        if stream_sink is not None and outcome.text:
            stream_sink(outcome.text)
        return outcome


def _tool_call(name: str, arguments: dict) -> dict:
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def _engine(store, prompts_dir, outcomes):
    from stockinsider.agent.loop import TurnEngine
    from stockinsider.agent.repl import build_registry

    return TurnEngine(store, build_registry(store), _Provider(outcomes), prompts_dir=prompts_dir)


def _run(engine, session_id, text, streamed=None, rendered=None):
    return engine.run_turn(
        session_id,
        text,
        profile="standard",
        render=(rendered.append if rendered is not None else lambda _t: None),
        progress=lambda _t: None,
        stream_sink=(streamed.append if streamed is not None else None),
    )


def test_regeneration_request_carries_the_conversation(session_store, prompts_dir) -> None:
    from stockinsider.agent.providers import ChatOutcome

    engine = _engine(
        session_store,
        prompts_dir,
        [
            ChatOutcome(text="Tencent reported results. It will surge tomorrow.", usage={}),
            ChatOutcome(text="Tencent reported results. Hypothesis: it might rise.", usage={}),
        ],
    )
    record = session_store.create(profile="standard")
    outcome = _run(engine, record["session_id"], "Will Tencent go up?", streamed=[])
    regen_call = engine._provider.seen_messages[1]  # noqa: SLF001 - white-box request assertion
    assert "You are a test analyst." in regen_call[0]["content"]  # identity travels
    assert {"role": "user", "content": "Will Tencent go up?"} in regen_call  # the question travels
    assert regen_call[-2] == {"role": "assistant", "content": "Tencent reported results."}  # stripped draft
    assert regen_call[-1]["role"] == "user" and regen_call[-1]["content"].startswith("[harness]")
    assert "INV-002" in regen_call[-1]["content"]
    assert engine._provider.seen_tools[1] is None  # noqa: SLF001 - no tool loop in the rewrite
    assert outcome.displayed == "Tencent reported results. Hypothesis: it might rise."


def test_regeneration_and_refusal_are_recorded(session_store, prompts_dir) -> None:
    from stockinsider.agent.providers import ChatOutcome

    engine = _engine(
        session_store,
        prompts_dir,
        [
            ChatOutcome(text="It will surge tomorrow.", usage={}),
            ChatOutcome(text="It might rise (hypothesis).", usage={}),
            ChatOutcome(text="It will surge tomorrow.", usage={}),
            ChatOutcome(text="It will definitely climb.", usage={}),  # still violating
        ],
    )
    record = session_store.create(profile="standard")
    first = _run(engine, record["session_id"], "outlook?")
    second = _run(engine, record["session_id"], "outlook again?")
    assert first.refused is False and second.refused is True
    assert second.displayed.startswith("refused:")
    records = [
        event
        for event in session_store.read_events(record["session_id"])
        if event.get("event") == "error" and event.get("kind") == "epistemic"
    ]
    assert [r["outcome"] for r in records] == ["regenerated", "refused"]
    assert records[0]["original"] == "It will surge tomorrow."
    assert records[0]["violations"] == ["It will surge tomorrow."]


def _seed_turns(store, session_id: str, turns: int, *, tools_per_turn: int = 0) -> None:
    for n in range(1, turns + 1):
        turn = f"turn-{n:04d}"
        store.append_event(session_id, {"event": "user-message", "text": f"question {n}", "turn": turn})
        for _ in range(tools_per_turn):
            store.append_event(
                session_id, {"event": "tool-call", "tool": "budget.query", "arguments": {}, "turn": turn}
            )
            store.append_event(
                session_id, {"event": "tool-result", "tool": "budget.query", "ok": True, "turn": turn}
            )
        store.append_event(session_id, {"event": "assistant-message", "text": f"answer {n}", "turn": turn})


def test_history_counts_messages_not_events(session_store, prompts_dir) -> None:
    from stockinsider.agent.providers import ChatOutcome

    engine = _engine(session_store, prompts_dir, [ChatOutcome(text="ok", usage={})])
    record = session_store.create(profile="standard")
    _seed_turns(session_store, record["session_id"], 5, tools_per_turn=2)  # 30 events
    _run(engine, record["session_id"], "what did you say first?")
    seen = engine._provider.seen_messages[0]  # noqa: SLF001
    assert {"role": "user", "content": "question 1"} in seen
    assert {"role": "assistant", "content": "answer 1"} in seen


def test_history_never_starts_mid_turn(session_store, prompts_dir) -> None:
    from stockinsider.agent.loop import HISTORY_WINDOW
    from stockinsider.agent.providers import ChatOutcome

    engine = _engine(session_store, prompts_dir, [ChatOutcome(text="ok", usage={})])
    record = session_store.create(profile="standard")
    _seed_turns(session_store, record["session_id"], HISTORY_WINDOW // 2 + 1)
    # a harness user-message without an answer shifts the window by one
    session_store.append_event(
        record["session_id"], {"event": "user-message", "text": "[harness] confirmed write executed", "turn": None}
    )
    _run(engine, record["session_id"], "now")
    seen = engine._provider.seen_messages[0]  # noqa: SLF001
    history = [m for m in seen if m["role"] != "system"]
    assert history[0]["role"] == "user"
    assert {"role": "assistant", "content": "answer 2"} not in seen  # its question was cut off


def test_truncated_history_is_announced(session_store, prompts_dir) -> None:
    from stockinsider.agent.loop import HISTORY_TRUNCATED_NOTE, HISTORY_WINDOW
    from stockinsider.agent.providers import ChatOutcome

    note = {"role": "system", "content": HISTORY_TRUNCATED_NOTE}
    engine = _engine(
        session_store, prompts_dir, [ChatOutcome(text="ok", usage={}), ChatOutcome(text="ok", usage={})]
    )
    exact = session_store.create(profile="standard")
    _seed_turns(session_store, exact["session_id"], HISTORY_WINDOW // 2)
    _run(engine, exact["session_id"], "now")
    assert note not in engine._provider.seen_messages[0]  # noqa: SLF001 - boundary: nothing cut
    over = session_store.create(profile="standard")
    _seed_turns(session_store, over["session_id"], HISTORY_WINDOW // 2 + 1)
    _run(engine, over["session_id"], "now")
    assert note in engine._provider.seen_messages[1]  # noqa: SLF001 - boundary + 1: announced


def test_quarantined_answer_is_explained_in_history(session_store, prompts_dir) -> None:
    """Live run: the degraded line read back as the model's own answer made it
    tell the user the news data had been unavailable."""
    from stockinsider.agent.providers import ChatOutcome

    engine = _engine(session_store, prompts_dir, [ChatOutcome(text="ok", usage={})])
    record = session_store.create(profile="standard")
    session_store.append_event(record["session_id"], {"event": "user-message", "text": "news?", "turn": "turn-0001"})
    session_store.append_event(
        record["session_id"],
        {"event": "assistant-message", "text": "data unavailable for: 10", "turn": "turn-0001", "post_check": "failed"},
    )
    _run(engine, record["session_id"], "and now?")
    seen = engine._provider.seen_messages[0]  # noqa: SLF001
    replayed = [m["content"] for m in seen if m["role"] == "assistant"]
    assert len(replayed) == 1
    assert replayed[0].startswith("[harness] This answer was withheld by the numeric post-check")
    assert replayed[0].endswith("data unavailable for: 10")


def test_prelude_separated_on_screen(session_store, prompts_dir) -> None:
    from stockinsider.agent.providers import ChatOutcome

    engine = _engine(
        session_store,
        prompts_dir,
        [
            ChatOutcome(text="Checking the budget.", tool_calls=[_tool_call("budget.query", {"profile": "quick"})]),
            ChatOutcome(text="Done checking.", usage={}),
        ],
    )
    record = session_store.create(profile="standard")
    streamed: list[str] = []
    outcome = _run(engine, record["session_id"], "budget?", streamed=streamed)
    screen = "".join(streamed)
    assert "Checking the budget.\nDone checking." in screen
    assert screen.strip() == outcome.displayed  # screen == record


def test_report_artifact_excludes_prelude(session_store, prompts_dir) -> None:
    from stockinsider.agent.providers import ChatOutcome
    from stockinsider.agent.repl import _run_report_turn

    engine = _engine(
        session_store,
        prompts_dir,
        [
            ChatOutcome(
                text="Understood, the watchlist update is recorded.",
                tool_calls=[_tool_call("budget.query", {"profile": "quick"})],
            ),
            ChatOutcome(text="Report body: deterministic reading, no forecast.", usage={}),
            ChatOutcome(text="It will surge tomorrow.", usage={}),
            ChatOutcome(text="It will definitely climb.", usage={}),
        ],
    )
    record = session_store.create(profile="standard", provenance={"model_id": "m", "prompt_version": "1"})
    lines: list[str] = []
    _run_report_turn(engine, session_store, record, "0700.HK", lines.append)
    artifacts = sorted((session_store.root / record["session_id"] / "artifacts").glob("report-*.md"))
    assert len(artifacts) == 1
    content = artifacts[0].read_text(encoding="utf-8")
    assert "Report body: deterministic reading" in content
    assert "Understood, the watchlist update" not in content
    # an INV-002 refusal is not a report
    refused_lines: list[str] = []
    _run_report_turn(engine, session_store, record, "0700.HK", refused_lines.append)
    assert any("refused by the epistemic filter" in line for line in refused_lines)
    assert len(list((session_store.root / record["session_id"] / "artifacts").glob("report-*.md"))) == 1


# ---- F6 / F7 / F10: sync honesty, daily benchmark refresh ---------------------------


def _weekdays(start: str, end: str) -> list[str]:
    day, stop = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while day <= stop:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


class _Vendor:
    """Offline vendor: weekday bars, optional per-symbol empties, holes and faults."""

    def __init__(self) -> None:
        self.empty: set[str] = set()
        self.fault: set[str] = set()
        self.hole: dict[str, tuple[str, str]] = {}
        self.calls: list[tuple[str, str, str]] = []

    def is_live(self) -> bool:
        return True

    def fetch_eod(self, symbol: str, from_date: str, to_date: str):
        self.calls.append((symbol, from_date, to_date))
        if symbol in self.fault:
            raise RuntimeError("vendor fault")
        if symbol in self.empty:
            return []
        days = _weekdays(from_date, to_date)
        if symbol in self.hole:
            lo, hi = self.hole[symbol]
            days = [d for d in days if not lo <= d <= hi]
        return [
            {"date": d, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "adjusted_close": 1.0, "volume": 1}
            for d in days
        ]


@pytest.fixture()
def sync_env(tmp_path, monkeypatch):
    from stockinsider.data import open_data_store
    from stockinsider.data.ingest import sync as sync_mod

    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setenv("EODHD_DAILY_CALLS", "1000")
    clock = {"today": "2026-09-04"}

    def _window(_self):
        today = date.fromisoformat(clock["today"])
        return (today - timedelta(days=sync_mod.BACKFILL_DAYS)).isoformat(), today.isoformat()

    monkeypatch.setattr(sync_mod.SyncService, "_window", _window)
    monkeypatch.setattr(sync_mod.SyncService, "_fundamentals_enabled", lambda _self: False)
    ds = open_data_store(str(tmp_path / "data"))
    with ds.conn:
        for symbol in ("OLDC.US", "NEWB.US"):
            ds.conn.execute(
                "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified,"
                " source, resolved_at) VALUES (?, 'US', ?, 'stock', '[]', 1, 'test', '2026-09-01T00:00:00+00:00')",
                (symbol, symbol),
            )
        ds.conn.execute(
            "INSERT INTO watchlist (canonical_symbol, added_at, added_via, status)"
            " VALUES ('OLDC.US', '2026-09-01T00:00:00+00:00', 'cli', 'active')"
        )
    yield ds, clock
    ds.close()


def _sync(ds, vendor):
    from stockinsider.data.ingest.sync import SyncService

    return SyncService(ds.conn, adapter=vendor, news_enabled=False).run().results


def _cursor(ds, symbol):
    row = ds.conn.execute("SELECT cursor FROM sync_state WHERE track = ?", (f"market:{symbol}",)).fetchone()
    return row["cursor"] if row else None


def _open_gaps(ds, symbol):
    return ds.conn.execute(
        "SELECT COUNT(*) FROM sync_gaps WHERE canonical_symbol = ? AND resolved_at IS NULL", (symbol,)
    ).fetchone()[0]


def test_empty_backfill_fails_and_keeps_cursor(sync_env) -> None:
    ds, _clock = sync_env
    vendor = _Vendor()
    vendor.empty.add("OLDC.US")
    item = next(r for r in _sync(ds, vendor) if r.symbol == "OLDC.US")
    assert item.action == "backfill" and item.status == "failed"
    assert "0 bars" in item.detail and "data through" not in item.detail
    assert _cursor(ds, "OLDC.US") is None
    vendor.empty.clear()
    retry = next(r for r in _sync(ds, vendor) if r.symbol == "OLDC.US")
    assert retry.action == "backfill" and retry.status == "ok"  # history is re-planned, not lost


def test_empty_incremental_fails_and_keeps_cursor(sync_env) -> None:
    ds, clock = sync_env
    vendor = _Vendor()
    _sync(ds, vendor)
    assert _cursor(ds, "OLDC.US") == "2026-09-04"
    clock["today"] = "2026-09-08"
    vendor.empty.add("OLDC.US")
    item = next(r for r in _sync(ds, vendor) if r.symbol == "OLDC.US")
    assert item.action == "incremental" and item.status == "failed"
    assert "data through" not in item.detail
    assert _cursor(ds, "OLDC.US") == "2026-09-04"


def test_benchmark_indices_refresh_daily(sync_env) -> None:
    ds, clock = sync_env
    vendor = _Vendor()
    _sync(ds, vendor)
    clock["today"] = "2026-09-08"
    refreshed = {(r.symbol, r.action, r.status) for r in _sync(ds, vendor) if r.symbol.endswith(".INDX")}
    for index in ("HSI.INDX", "HSTECH.INDX", "GSPC.INDX", "NDX.INDX"):
        assert (index, "incremental", "ok") in refreshed
    latest = ds.conn.execute("SELECT MAX(date) FROM market_bars WHERE canonical_symbol = 'GSPC.INDX'").fetchone()[0]
    assert latest == "2026-09-08"
    # boundary: cursor == today -> no index incremental
    again = [r for r in _sync(ds, vendor) if r.symbol.endswith(".INDX")]
    assert again == []


def test_late_hole_detected_after_index_refresh(sync_env) -> None:
    ds, clock = sync_env
    vendor = _Vendor()
    _sync(ds, vendor)  # first backfill on 2026-09-04
    clock["today"] = "2026-09-18"
    vendor.hole["OLDC.US"] = ("2026-09-08", "2026-09-11")
    _sync(ds, vendor)
    assert _open_gaps(ds, "OLDC.US") == 1  # the hole behind the cursor is now visible
    vendor.hole.clear()
    clock["today"] = "2026-09-21"
    repair = next(r for r in _sync(ds, vendor) if r.symbol == "OLDC.US" and r.action == "gap-repair")
    assert repair.status == "ok"
    stored = ds.conn.execute(
        "SELECT COUNT(*) FROM market_bars WHERE canonical_symbol = 'OLDC.US'"
        " AND date BETWEEN '2026-09-08' AND '2026-09-11'"
    ).fetchone()[0]
    assert stored == 4


def test_detection_stops_at_cursor(sync_env) -> None:
    ds, clock = sync_env
    vendor = _Vendor()
    _sync(ds, vendor)
    clock["today"] = "2026-09-18"
    vendor.fault.add("OLDC.US")  # its incremental fails; the calendar still advances
    _sync(ds, vendor)
    latest = ds.conn.execute("SELECT MAX(date) FROM market_bars WHERE canonical_symbol = 'GSPC.INDX'").fetchone()[0]
    assert latest == "2026-09-18"  # the calendar DID move past the symbol's cursor
    assert _cursor(ds, "OLDC.US") == "2026-09-04"
    # the unfetched days after the cursor are the incremental's job, not gaps
    assert _open_gaps(ds, "OLDC.US") == 0


def test_no_data_gaps_visible_in_status(sync_env) -> None:
    from stockinsider.agent.registry import Registry, register_sync_tools
    from stockinsider.agent.repl import _cmd_sync
    from stockinsider.data.ingest.sync import sync_status

    ds, _clock = sync_env
    with ds.conn:
        ds.conn.execute(
            "INSERT INTO sync_gaps (canonical_symbol, from_date, to_date, detected_at, resolved_at, resolution)"
            " VALUES ('OLDC.US', '2025-01-06', '2025-01-10', '2026-09-01', '2026-09-03', 'no-data')"
        )
    status = sync_status(ds.conn)
    assert status["pending_gaps"] == []
    assert status["no_data_gaps"] == [
        {"canonical_symbol": "OLDC.US", "from_date": "2025-01-06", "to_date": "2025-01-10", "resolved_at": "2026-09-03"}
    ]
    registry = Registry()
    register_sync_tools(registry, ds)
    lines: list[str] = []
    _cmd_sync(registry, ["status"], lines.append)
    assert any("no-data: OLDC.US 2025-01-06..2025-01-10" in line for line in lines)


# ---- BD-025: the AI-use log must stay machine-readable --------------------------------


def _aiuse_gate():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "checks"))
    try:
        import aiuse_gate
    finally:
        sys.path.pop(0)
    return aiuse_gate


def test_aiuse_log_structure_is_checked() -> None:
    gate = _aiuse_gate()
    good = "schema: 1\nsessions:\n  - id: AILOG-0001\n    date: '2026-09-30'\n  - id: AILOG-0002\n"
    assert gate.log_structure_errors(good) == []
    # the PR #54 shape: an entry appended at column 0 breaks the document
    broken = good + "- id: AILOG-0003\n  date: '2026-09-30'\n"
    assert gate.log_structure_errors(broken)[0].startswith("not parseable as YAML")
    duplicate = good + "  - id: AILOG-0002\n"
    assert gate.log_structure_errors(duplicate) == ["duplicate id AILOG-0002"]
    malformed = good + "  - id: AILOG-7\n"
    assert gate.log_structure_errors(malformed) == ["entry #3 has a malformed id: 'AILOG-7'"]


def test_repository_aiuse_log_is_well_formed() -> None:
    gate = _aiuse_gate()
    log = Path(__file__).resolve().parents[2] / "docs" / "ai-use-log.yaml"
    assert gate.log_structure_errors(log.read_text(encoding="utf-8")) == []


# ---- F9: static arithmetic gate -----------------------------------------------------


def _gate_scan(files: dict[str, str]) -> set[str]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "checks"))
    try:
        from static_arithmetic import scan
    finally:
        sys.path.pop(0)
    with tempfile.TemporaryDirectory() as tmp:
        package = Path(tmp) / "src" / "stockinsider" / "agent"
        package.mkdir(parents=True)
        for name, body in files.items():
            (package / name).write_text(body, encoding="utf-8")
        return {entry.split(":")[0].rsplit("/", 1)[-1] for entry in scan(Path(tmp))}


def test_static_gate_catches_remaining_idioms() -> None:
    files = {
        "aug_assign.py": (
            'def f(rows):\n    total = 0\n    for r in rows:\n        total += r["close"]\n    return total\n'
        ),
        "sum_builtin.py": 'def f(rows):\n    return sum(r["close"] for r in rows)\n',
        "stats_mean.py": 'import statistics\n\n\ndef f(rows):\n    return statistics.mean(r["close"] for r in rows)\n',
        "method_call.py": 'def f(frame):\n    return frame["close"].pct_change()\n',
        "comprehension_alias.py": (
            'def f(rows):\n    closes = [r["close"] for r in rows]\n    return closes[-1] / closes[0]\n'
        ),
        "default_key.py": 'def f(row, prev, k="close"):\n    return row[k] - prev[k]\n',
    }
    assert _gate_scan(files) == set(files)


def test_static_gate_ignores_string_formatting() -> None:
    files = {
        "fstring.py": 'def f(last):\n    line = "x"\n    line += f" | volume {last[\'volume\']}"\n    return line\n',
        "filter.py": 'def f(rows):\n    kept = [r for r in rows if r["close"] > 0]\n    return len(kept) + 1\n',
    }
    assert _gate_scan(files) == set()
