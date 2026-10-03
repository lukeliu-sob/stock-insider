"""TP-018 adversarial suite: third-audit remediation (P0/P1/P2).  lang-fixture: intentional-cjk

Every fix from the third review report carries at least one
negative/adversarial test here (docs/test-plans/TP-018.md). The
INV-002 battery section is authored from the AUDITOR'S sentence
classes, not the pattern writer's, per E-007's author-separation
requirement.

Implements: REQ-SI-INV-001, REQ-SI-INV-002, REQ-SI-INV-003,
REQ-SI-INV-004, REQ-SI-SEC-003 (ADR-004 Am2, ADR-005 Am3, ADR-006 Am5/Am6)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stockinsider.agent.confirm import ConfirmationBroker
from stockinsider.agent.guardrail import epistemic_filter, postcheck_numbers
from stockinsider.agent.loop import TurnEngine, load_identity_prompt
from stockinsider.agent.providers import ChatOutcome, ProviderError
from stockinsider.agent.repl import _CONFIRM_LINE, build_registry
from stockinsider.agent.session import SessionError, SessionStore
from stockinsider.shared.events import EventValidationError

from test_streaming import ScriptedProvider

IDENTITY = """---
version: 1
artifact: identity
---

# Test identity

You are a test analyst.
"""


@pytest.fixture()
def prompts_dir(tmp_path) -> Path:
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "identity.md").write_text(IDENTITY, encoding="utf-8")
    return directory


@pytest.fixture()
def store(tmp_path) -> SessionStore:
    return SessionStore(root=tmp_path / "sessions")


def make_engine(store: SessionStore, outcomes: list[ChatOutcome], prompts_dir: Path) -> TurnEngine:
    return TurnEngine(store, build_registry(store), ScriptedProvider(outcomes), prompts_dir=prompts_dir)


def tool_call(name: str, arguments: dict) -> dict:
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class Spy:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, text: str) -> None:
        self.lines.append(text)


# ---- H3: token alphabet, non-relay, strict routing, expiry ------------------


def test_tokens_are_eight_lowercase_letters() -> None:
    """H3-1: digit-bearing tokens died in model prose; letters cannot."""
    broker = ConfirmationBroker()
    tokens = {broker.issue("s", "watchlist.add", {"canonical_symbol": "0700.HK"}) for _ in range(64)}
    assert all(len(t) == 8 and t.isalpha() and t.islower() for t in tokens)
    assert all(postcheck_numbers(f"please confirm {t}", {}).passed for t in list(tokens)[:4])


def test_write_gate_progress_and_model_message(store, prompts_dir) -> None:
    outcomes = [
        ChatOutcome(
            tool_calls=[tool_call("watchlist.add", {"canonical_symbol": "0700.HK"})],
            usage={},
        ),
        ChatOutcome(text="The addition is proposed; please confirm in the terminal.", usage={}),
    ]
    registry = build_registry(store)
    from stockinsider.shared.tools import EffectClass, SourceKind, ToolSpec

    registry.register(
        ToolSpec(
            name="watchlist.add",
            description="test write tool",
            arguments_spec={"canonical_symbol": "str"},
            result_spec="dict",
            effect_class=EffectClass.WRITE,
            source_kind=SourceKind.API,
        ),
        lambda args: {"added": args["canonical_symbol"]},
    )
    engine = TurnEngine(store, registry, ScriptedProvider(outcomes), prompts_dir=prompts_dir)
    record = store.create(profile="standard")
    spy = Spy()
    outcome = engine.run_turn(
        record["session_id"], "add 0700", profile="standard", render=spy, progress=spy, stream_sink=None
    )
    progress_text = " ".join(spy.lines)
    assert "pending write confirmation: watchlist.add" in progress_text
    assert "'confirm " in progress_text  # the token + usage instruction
    # the model-facing failure must NOT carry the token
    events = store.read_events(record["session_id"])
    tool_results = [e for e in events if e["event"] == "tool-result" and not e["ok"]]
    assert tool_results, "write interception must produce a failed tool-result"
    assert "do NOT repeat" in tool_results[0]["error"]
    token_line = next(line for line in spy.lines if "'confirm " in line)
    token = token_line.split("'confirm ")[1].split("'")[0]
    assert _CONFIRM_LINE.match(f"confirm {token}")
    # non-relay: the token appears ONLY in the chrome line, never in any
    # model-facing or logged error text
    assert token not in tool_results[0]["error"]
    assert outcome.quarantined is False


def test_confirm_line_routing_is_strict() -> None:
    """H3-6: questions starting with 'confirm' are conversation, not commands."""
    assert _CONFIRM_LINE.match("confirm abcdefgh")
    assert not _CONFIRM_LINE.match("confirm how do I add a stock?")
    assert not _CONFIRM_LINE.match("confirm ABCDEFGH")  # case-sensitive token
    assert not _CONFIRM_LINE.match("confirm abcd1234")  # digits never issued
    assert not _CONFIRM_LINE.match("confirmation of what?")


def test_tokens_expire_at_turn_boundaries(store, prompts_dir) -> None:
    """H3-5: expire_turns runs every run_turn; stale tokens die."""
    engine = TurnEngine(store, build_registry(store), ScriptedProvider([]), prompts_dir=prompts_dir)
    token = engine.confirmations.issue("sess", "watchlist.add", {}, turn=1)
    engine.confirmations.expire_turns(5, max_age=3)
    assert engine.confirmations.consume(token) is None


# ---- H1 residual: prelude text is validated and recorded --------------------


def test_fabricated_prelude_number_flagged(store, prompts_dir) -> None:
    """The old hole: pre-tool prose streamed through unvalidated.

    TP-023 (ADR-008 requirement change): the prelude's fabricated number is
    shown only with the marker, instead of withholding the answer.
    """
    outcomes = [
        ChatOutcome(
            text="Let me check. The current price is 999.99.",
            tool_calls=[tool_call("budget.query", {"profile": "quick"})],
            usage={},
        ),
        ChatOutcome(text="The budget is 30000 tokens.", usage={}),
    ]
    engine = make_engine(store, outcomes, prompts_dir)
    record = store.create(profile="quick")
    spy = Spy()
    outcome = engine.run_turn(
        record["session_id"], "budget?", profile="quick", render=spy, progress=spy, stream_sink=None
    )
    assert outcome.quarantined is False
    assert outcome.unverified == ["999.99"]
    assert "999.99[?]" in outcome.displayed  # marked where it appears, never bare
    assert outcome.displayed.count("999.99") == 1
    # screen == record: the stored assistant text matches what was displayed
    events = store.read_events(record["session_id"])
    stored = [e for e in events if e["event"] == "assistant-message"][-1]
    assert stored["text"] == outcome.displayed


def test_clean_prelude_displayed_and_recorded(store, prompts_dir) -> None:
    outcomes = [
        ChatOutcome(
            text="Checking the budget for you.",
            tool_calls=[tool_call("budget.query", {"profile": "quick"})],
            usage={},
        ),
        ChatOutcome(text="The quick budget is 30000 tokens.", usage={}),
    ]
    engine = make_engine(store, outcomes, prompts_dir)
    record = store.create(profile="quick")
    spy = Spy()
    outcome = engine.run_turn(
        record["session_id"], "budget?", profile="quick", render=spy, progress=spy, stream_sink=None
    )
    assert outcome.quarantined is False
    assert "Checking the budget" in outcome.displayed
    assert "30000" in outcome.displayed
    events = store.read_events(record["session_id"])
    stored = [e for e in events if e["event"] == "assistant-message"][-1]
    assert stored["text"] == outcome.displayed


# ---- M5 residual + H2b: turn-scoped ledger keys, ledger-wide recheck --------


def test_cross_turn_restatement_survives_a_second_symbol(store, prompts_dir) -> None:
    """A6b shape: turn 1 queries 0700, turn 2 queries 9988, turn 3 restates
    turn 1's close — the old ledger evicted it (same-key collision)."""
    engine = make_engine(store, [], prompts_dir)
    record = store.create(profile="standard")

    # Turn 1: snapshot with market.quote#1 = 436.6
    store.snapshot(record["session_id"], "turn-0001", {"turn-0001/market.quote#1": {"close": 436.6}})
    # Turn 2: snapshot with market.quote#1 = 88.4 under the SAME old-style key
    # is the bug; the engine now writes turn-scoped keys.
    store.snapshot(record["session_id"], "turn-0002", {"turn-0002/market.quote#1": {"close": 88.4}})
    ledger = engine._session_ledger(record["session_id"])
    assert ledger["turn-0001/market.quote#1"]["close"] == 436.6
    assert ledger["turn-0002/market.quote#1"]["close"] == 88.4
    check = postcheck_numbers("The close was 436.6.", ledger)
    assert check.passed, check.failed


# ---- H4 residual: abort persists; resume refused -----------------------------


def _three_epistemic_violations(store, prompts_dir):
    # TP-023 (ADR-008 requirement change): the INV-001 abort is retired, so
    # the sticky-abort property is driven by the INV-002 budget (> 2)
    outcomes = []
    for _ in range(3):
        outcomes += [
            ChatOutcome(text="BYD will surge.", usage={}),
            ChatOutcome(text="Hypothesis: BYD might rise.", usage={}),
        ]
    engine = make_engine(store, outcomes, prompts_dir)
    record = store.create(profile="standard")
    spy = Spy()
    for i in range(3):
        engine.run_turn(record["session_id"], f"q{i}", profile="standard", render=spy, progress=spy)
    return engine, record


def test_abort_persists_and_resume_refused(store, prompts_dir) -> None:
    engine, record = _three_epistemic_violations(store, prompts_dir)
    assert engine.run_turn  # engine alive
    row = next(r for r in store.list_sessions() if r["session_id"] == record["session_id"])
    assert row["status"] == "aborted"
    store.close(record["session_id"])  # housekeeping must not pardon
    row = next(r for r in store.list_sessions() if r["session_id"] == record["session_id"])
    assert row["status"] == "aborted"
    with pytest.raises(SessionError, match="aborted"):
        store.resume(record["session_id"])


# ---- new-4: egress crash path closed ----------------------------------------


def test_provider_wraps_egress_violation_into_provider_error() -> None:
    from stockinsider.agent.providers import OpenAICompatibleProvider, ProviderConfig

    config = ProviderConfig(
        chat_base_url="https://evil.example.com/v1",
        chat_model="m",
        embedding_base_url=None,
        embedding_model=None,
    )
    provider = OpenAICompatibleProvider(config, api_key="k")
    with pytest.raises(ProviderError, match="egress whitelist"):
        provider.chat([{"role": "user", "content": "hi"}])


def test_extra_hosts_extend_the_allowlist(monkeypatch) -> None:
    from stockinsider.shared.egress import validate_egress_url

    monkeypatch.setenv("EGRESS_EXTRA_HOSTS", "openrouter.ai, Localhost ")
    from stockinsider.shared.egress import extra_hosts_from_env

    extra = extra_hosts_from_env()
    assert "openrouter.ai" in extra and "localhost" in extra
    validate_egress_url("https://openrouter.ai/v1", extra_allowed=extra)


def test_config_set_rejects_non_whitelisted_endpoint(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from stockinsider.cli.app import app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["config", "set", "--chat-base-url", "https://evil.example.com/v1"])
    assert result.exit_code == 2
    assert "egress" in result.output.lower()


# ---- new-5: heading ordinals -------------------------------------------------


def test_three_digit_heading_number_is_checked() -> None:
    check = postcheck_numbers("## 850 HKD fair value", {"q": {"close": 12.3}})
    assert check.failed == ["850"]


def test_two_digit_heading_ordinal_still_layout() -> None:
    check = postcheck_numbers("## 12. Data quality\n## 6 Conclusion", {})
    assert check.passed


# ---- low-4: zero-bar gap repair ---------------------------------------------


def _gap_repair_engine(conn, gap_key: tuple[str, str, str]):
    """Minimal SyncService wiring: _execute with a dead adapter returning [].

    Real sqlite connection (DE-08, TP-026 plan: the old hand-rolled fake
    matched SQL by string prefix with positional params, which broke the
    moment the per-day gating added a bind parameter - a real connection
    has no such fragility and lets the per-day behavior be driven by
    actually changing empty_attempts_date between calls).
    """
    from stockinsider.data.ingest.sync import SyncService

    engine = SyncService.__new__(SyncService)

    class _Budget:
        def try_spend(self, cost):
            return True

    engine._budget = _Budget()

    class _Adapter:
        def fetch_eod(self, symbol, from_date, to_date):
            return []

    engine._adapter = _Adapter()
    engine._conn = conn
    engine._cursor = lambda symbol: "2026-01-01"  # noqa: E731
    engine._set_cursor = lambda symbol, d: None
    with conn:
        conn.execute(
            "INSERT INTO sync_gaps (canonical_symbol, from_date, to_date, detected_at) VALUES (?, ?, ?, ?)",
            (*gap_key, "2026-01-01T00:00:00+00:00"),
        )
    return engine


def _gap_row(conn, gap_key: tuple[str, str, str]):
    return conn.execute(
        "SELECT empty_attempts, empty_attempts_date, resolved_at, resolution FROM sync_gaps "
        "WHERE canonical_symbol = ? AND from_date = ? AND to_date = ?",
        gap_key,
    ).fetchone()


def test_zero_bar_gap_repair_three_attempts_then_terminal(tmp_path) -> None:
    """Fourth-audit high finding: unfillable gaps must CLOSE honestly
    (attempt-counted, resolution='no-data') instead of retrying forever
    and starving the daily budget - and must not be marked repaired.
    DE-08 (TP-026 plan): an attempt counts once per calendar day, so each
    of these three attempts is backdated to a distinct, already-passed
    day before the call - three DIFFERENT days of empty results, not
    three quick same-day re-runs (see the sibling same-day test)."""
    from stockinsider.data.store.db import open_db

    conn = open_db(tmp_path / "data")
    key = ("0700.HK", "2026-01-02", "2026-01-05")
    engine = _gap_repair_engine(conn, key)
    for attempt, backdated_day in enumerate(("2025-01-01", "2025-01-02", "2025-01-03"), start=1):
        with conn:
            conn.execute(
                "UPDATE sync_gaps SET empty_attempts_date = ? "
                "WHERE canonical_symbol = ? AND from_date = ? AND to_date = ?",
                (backdated_day, *key),
            )
        result = engine._execute((key[0], "gap-repair", key[1], key[2]), None)
        row = _gap_row(conn, key)
        if attempt < 3:
            assert result.status == "failed"
            assert f"({attempt}/3 attempts" in result.detail
            assert row["resolved_at"] is None
        else:
            assert result.status == "failed"
            assert "confirmed no-data" in result.detail
            assert row["resolution"] == "no-data"
            assert row["resolved_at"] is not None
        assert row["empty_attempts"] == attempt


def test_zero_bar_gap_repair_same_day_retries_count_once(tmp_path) -> None:
    """DE-08 (TP-026 plan), the negative case: three quick re-runs on the
    SAME day must not exhaust MAX_EMPTY_ATTEMPTS by themselves - the gap
    needs three DIFFERENT days of empty results, not three calls."""
    from stockinsider.data.store.db import open_db

    conn = open_db(tmp_path / "data")
    key = ("0700.HK", "2026-01-02", "2026-01-05")
    engine = _gap_repair_engine(conn, key)
    for _ in range(3):
        result = engine._execute((key[0], "gap-repair", key[1], key[2]), None)
        assert result.status == "failed"
        assert "(1/3 attempts" in result.detail
    row = _gap_row(conn, key)
    assert row["empty_attempts"] == 1  # three same-day calls, one counted attempt
    assert row["resolved_at"] is None  # nowhere near MAX_EMPTY_ATTEMPTS yet


# ---- M4: language allowlist ---------------------------------------------------


def test_non_latin_scripts_fail_closed() -> None:
    from stockinsider.shared.language import is_english_only

    assert not is_english_only("Выручка выросла на 5%")  # Cyrillic
    assert not is_english_only("매출이 5% 증가")  # Hangul
    assert not is_english_only("Τιμή μερισμάτων 5%")  # Greek
    assert not is_english_only("市值上涨")  # CJK (still caught)
    assert is_english_only("Adjusted close 436.60 — up 1.2% (±0.01)")


# ---- M2 phase 1: OHLCV typed provenance ---------------------------------------


QUOTE_POOL = {
    "turn-0001/market.quote#1": {
        "symbol": "0700.HK",
        "open": 430.0,
        "high": 440.0,
        "low": 428.0,
        "close": 436.6,
        "volume": 12345678,
    }
}


def test_open_quoted_as_close_fails() -> None:
    check = postcheck_numbers("The open was 436.6.", QUOTE_POOL)
    assert not check.passed
    assert check.field_mismatch == ["436.6"]


def test_correct_field_quote_passes() -> None:
    assert postcheck_numbers("The open was 430.0.", QUOTE_POOL).passed
    assert postcheck_numbers("The close was 436.6.", QUOTE_POOL).passed
    assert postcheck_numbers("Volume reached 12345678 shares.", QUOTE_POOL).passed


def test_doji_open_equals_close_passes() -> None:
    pool = {"turn-0001/market.quote#1": {"open": 436.6, "close": 436.6}}
    assert postcheck_numbers("The open was 436.6.", pool).passed


def test_bare_number_without_field_mention_passes() -> None:
    assert postcheck_numbers("It traded at 436.6.", QUOTE_POOL).passed


# ---- M3: attribution exemption + modal recall ---------------------------------


def test_reported_speech_exempt() -> None:
    result = epistemic_filter("Management said it will increase the dividend.")
    assert result.passed
    assert epistemic_filter("According to the filing, shares will be delisted.").passed


def test_modal_certainty_classes_caught() -> None:
    for sentence in (
        "The stock is likely to rise after the results.",
        "Shares are set to climb on the news.",
        "The price is on track to fall further.",
        "Earnings are poised to surge next quarter.",
    ):
        assert epistemic_filter(sentence).violations, sentence


# ---- low-1/low-2/low-3: argument JSON, event validation, prompts path --------


def test_malformed_tool_arguments_fail_explicitly(store, prompts_dir) -> None:
    bad = {
        "id": "call-bad",
        "type": "function",
        "function": {"name": "budget.query", "arguments": "{not json"},
    }
    outcomes = [
        ChatOutcome(tool_calls=[bad], usage={}),
        ChatOutcome(text="That call was rejected: the arguments were malformed.", usage={}),
    ]
    engine = make_engine(store, outcomes, prompts_dir)
    record = store.create(profile="quick")
    spy = Spy()
    outcome = engine.run_turn(record["session_id"], "budget?", profile="quick", render=spy, progress=spy)
    events = store.read_events(record["session_id"])
    failed_results = [e for e in events if e["event"] == "tool-result" and not e["ok"]]
    assert failed_results and "malformed tool arguments" in failed_results[0]["error"]
    assert outcome.quarantined is False


def test_append_event_validates_kind(store) -> None:
    record = store.create(profile="standard")
    with pytest.raises(EventValidationError, match="unknown event kind"):
        store.append_event(record["session_id"], {"event": "user-confirmation"})
    with pytest.raises(SessionError, match="unknown session"):
        store.append_event("20990101T000000Z-nope", {"event": "user-message", "text": "x"})


def test_identity_prompt_resolves_from_package_root() -> None:
    version, body = load_identity_prompt()
    assert version.startswith("identity-")
    assert body  # found without depending on cwd


# ---- E-007 adversarial battery (auditor-authored classes) ---------------------


#: Sentences DERIVED FROM the violation CLASSES the third-party audit
#: reported (authorship honesty, E-007a: these are adaptations written
#: by the remediation author from the audit's described classes, not
#: verbatim auditor sentences - a truly auditor-authored held-out set
#: remains the reviewer's to run). Violating: must be stripped or
#: refused. Reported/attributed: must pass (factual reporting).
AUDIT_VIOLATING = [
    "The price will increase tomorrow.",
    "Shares will definitely fall after the announcement.",
    "It is going to drop sharply.",
    "Therefore the stock will rally.",
    "The stock is likely to surge on this news.",
    "Earnings are forecast to jump next quarter.",
    "Without doubt the index climbs from here.",
    "Expect shares to plummet once the lockup ends.",
    "The price is set to collapse when rates rise.",
    "This proves the rally will continue.",
]
AUDIT_REPORTED = [
    "Management said it will increase the dividend.",
    "The company announced that revenue will decline.",
    "According to the release, the stock will be added to the index.",
    "Guidance indicates the price will recover, the filing states.",
]


def test_audit_battery_recall() -> None:
    missed = [s for s in AUDIT_VIOLATING if not epistemic_filter(s).violations]
    assert not missed, f"audit violations passed: {missed}"


def test_audit_battery_reported_speech() -> None:
    flagged = [s for s in AUDIT_REPORTED if epistemic_filter(s).violations]
    assert not flagged, f"reported speech wrongly flagged: {flagged}"
