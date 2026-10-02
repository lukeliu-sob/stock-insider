"""TP-018b adversarial suite: fourth-audit remediation.

One negative/adversarial test per fourth-report finding
(docs/test-plans/TP-018.md amendment). Covers the sync starvation
fix, the widened language allowlist, snake_case field recognition,
identifier-code extraction, deferred regeneration streaming, the
narrowed attribution exemption, the empty-body gate, loopback HTTP,
resume-peek ordering, the verified-records migration, and the
extended static arithmetic gate.

Implements: REQ-SI-FR-001, REQ-SI-FR-014, REQ-SI-INV-001,
REQ-SI-INV-002, REQ-SI-INV-003, REQ-SI-SEC-003 (ADR-004 Am2,
ADR-006 Am6; TP-018b)
"""

from __future__ import annotations

import sqlite3

import pytest

from stockinsider.agent.guardrail import epistemic_filter, postcheck_numbers
from stockinsider.shared.language import is_english_only

# ---- 1. sync: budget starvation (fourth-audit high finding) ------------------


def _store_with_gaps(tmp_path):
    from stockinsider.data.store.schema import MIGRATIONS

    conn = sqlite3.connect(tmp_path / "s.db")
    for migration in MIGRATIONS:
        conn.executescript(migration)
    conn.row_factory = sqlite3.Row
    return conn


def test_detection_window_clips_to_earliest_bar(tmp_path) -> None:
    """Pre-listing dates never become gap rows: detection starts at the
    symbol's first stored bar."""
    from stockinsider.data.ingest.sync import SyncService

    conn = _store_with_gaps(tmp_path)
    svc = SyncService.__new__(SyncService)
    svc._conn = conn
    # listed 2025-01-06 (two bars), window start 5y back
    conn.execute(
        "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, verified, source, resolved_at) "
        "VALUES ('0700.HK', 'HK', 'Tencent', 'stock', 1, 'test', '2026-01-01')"
    )
    conn.executemany(
        "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close, "
        "volume, currency, source, fetched_at) "
        "VALUES ('0700.HK', ?, 1, 1, 1, 1, 1, 'HKD', 'test', '2026-01-01')",
        [("2025-01-06",), ("2025-01-07",)],
    )
    assert svc._detection_start("0700.HK", "2021-01-01") == "2025-01-06"
    # no bars at all: detection skipped (backfill populates first)
    assert svc._detection_start("9988.HK", "2021-01-01") is None
    conn.close()


def test_gap_budget_share_defers_excess_gaps(tmp_path) -> None:
    """gap-repair may consume at most half the daily cap per run; the
    excess defers explicitly and incrementals still execute."""
    from stockinsider.data.ingest.sync import SyncService

    conn = _store_with_gaps(tmp_path)
    svc = SyncService.__new__(SyncService)
    svc._conn = conn

    class _Budget:
        def __init__(self):
            self.spent = 0

        def try_spend(self, n=1):
            if self.spent + n > 20:
                return False
            self.spent += n
            return True

        def used_today(self):
            return self.spent

        def remaining(self):
            return 20 - self.spent

    svc._budget = _Budget()

    class _EmptyAdapter:
        def fetch_eod(self, symbol, from_date, to_date):
            return []

    svc._adapter = _EmptyAdapter()

    # simulate the run-loop quota bookkeeping with 30 queued gaps
    from stockinsider.data.ingest.sync import GAP_BUDGET_SHARE

    quota = max(1, int((svc._budget.remaining() + svc._budget.used_today()) * GAP_BUDGET_SHARE))
    assert quota == 10
    gap_spent = 0
    executed = deferred = 0
    for item in [("0700.HK", "gap-repair", "2025-01-01", "2025-01-02")] * 30:
        if item[1] == "gap-repair" and gap_spent >= quota:
            deferred += 1
            continue
        before = svc._budget.used_today()
        svc._execute(item, None)
        gap_spent += svc._budget.used_today() - before
        executed += 1
    assert executed == 10 and deferred == 20
    assert svc._budget.remaining() == 10  # half the cap preserved
    conn.close()


def test_v6_migration_demotes_secondary_verified_rows(tmp_path) -> None:
    """Pre-existing XETRA/MX rows verified=1 before ADR-005 Am2 lose the
    flag on migration; HK/US rows keep it."""
    from stockinsider.data.store.schema import MIGRATIONS

    conn = sqlite3.connect(tmp_path / "m.db")
    conn.executescript(MIGRATIONS[0])
    conn.executemany(
        "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, verified, source, resolved_at) "
        "VALUES (?, ?, 'x', 'stock', 1, 'test', '2026-01-01')",
        [("AAPL.US", "US"), ("SAP.DE", "XETRA"), ("TSLA.MX", "MX"), ("0700.HK", "HK")],
    )
    for migration in MIGRATIONS[1:]:
        conn.executescript(migration)
    rows = dict(conn.execute("SELECT canonical_symbol, verified FROM symbols").fetchall())
    assert rows == {"AAPL.US": 1, "SAP.DE": 0, "TSLA.MX": 0, "0700.HK": 1}
    conn.close()


# ---- 2. language allowlist widened -------------------------------------------


def test_common_prose_symbols_pass() -> None:
    assert is_english_only("2026-09-25 " + chr(0x2192) + " 2026-09-29")
    assert is_english_only(chr(0x2022) + " margin " + chr(0x2265) + " 30%")
    assert is_english_only("change " + chr(0x2191) + " 3% / " + chr(0x2193) + " 2%")
    assert is_english_only(chr(0x160) + "koda works; oe " + chr(0x153))
    assert is_english_only(
        "signal "
        + chr(0x2705)
        + " "
        + chr(0x274C)
        + " "
        + chr(0x26A0)
        + chr(0xFE0F)
        + " "
        + chr(0x1F4C8)
        + " "
        + chr(0x1F4C9)
    )


def test_non_latin_still_fails_closed() -> None:
    assert not is_english_only(chr(0x41F) + "rivet 5%")  # Cyrillic
    assert not is_english_only(chr(0xD55C) + chr(0xAD6D))  # Hangul
    assert not is_english_only(chr(0x5E02) + chr(0x573A))  # CJK


# ---- 3. snake_case field recognition ------------------------------------------


QUOTE_POOL = {
    "turn-0001/market.quote#1": {
        "close": 650.0,
        "adjusted_close": 642.8959,
        "volume": 12345678,
        "open": 640.0,
    }
}


def test_model_authored_table_passes() -> None:
    table = "| close | 650.0 |\n| adjusted_close | 642.8959 |\n| volume | 12345678 |\n| open | 640.0 |"
    check = postcheck_numbers(table, QUOTE_POOL)
    assert check.passed, check.field_mismatch


def test_field_swap_in_prose_still_caught() -> None:
    assert not postcheck_numbers("the open was 650.0", QUOTE_POOL).passed


# ---- 4. identifier codes are not numerics -------------------------------------


def test_reference_ids_not_extracted() -> None:
    assert postcheck_numbers("Per ADR-005 Am2 the flow works.", {}).failed == []
    assert postcheck_numbers("withheld under GOV-001 policy", {}).failed == []
    assert postcheck_numbers("see TP-018 and BD-016", {}).failed == []
    # a bare negative number is still a numeric claim
    assert postcheck_numbers("down -5 points", {}).failed == ["-5"]


# ---- 5. heading numbers (two-digit unpunctuated) -------------------------------


def test_two_digit_unpunctuated_heading_checked() -> None:
    assert postcheck_numbers("## 85 USD price target", {}).failed == ["85"]
    assert postcheck_numbers("## 6 Summary", {}).passed
    assert postcheck_numbers("## 12. Data", {}).passed


# ---- 6. INV-002: narrowed attribution + expected-to ----------------------------


def test_attribution_laundering_blocked() -> None:
    for sentence in (
        "According to the chart, the stock will rise next month.",
        "According to this analysis, the price will double.",
        "The release of earnings means shares will jump.",  # noun w/o speech act
    ):
        assert epistemic_filter(sentence).violations, sentence


def test_true_reported_speech_still_exempt() -> None:
    for sentence in (
        "Management said it will increase the dividend.",
        "The company announced that revenue will decline.",
        "According to the filing, shares will be delisted.",
    ):
        assert not epistemic_filter(sentence).violations, sentence


def test_expected_to_class_caught() -> None:
    for sentence in (
        "The price is expected to reach 500 next month.",
        "Earnings are predicted to exceed estimates.",
        "Shares are projected to double after the split.",
    ):
        assert epistemic_filter(sentence).violations, sentence


# ---- 7. egress: loopback HTTP allowed, others refused --------------------------


def test_loopback_http_allowed_remote_http_refused() -> None:
    from stockinsider.shared.egress import EgressViolationError, validate_egress_url

    validate_egress_url("http://localhost:11434/v1")
    validate_egress_url("http://127.0.0.1:8000/v1")
    for url in ("http://openrouter.ai/v1", "http://10.0.0.5:8080/v1", "ftp://eodhd.com/x"):
        with pytest.raises(EgressViolationError):
            validate_egress_url(url)


# ---- 8. empty PR body in PR context fails the gate -----------------------------


def test_empty_body_in_pr_context_fails(tmp_path, monkeypatch) -> None:
    import importlib.util

    from pathlib import Path as P

    gate_src = tmp_path / "tools" / "checks"
    gate_src.mkdir(parents=True)
    source = P(__file__).resolve().parents[2] / "tools" / "checks" / "testplan_gate.py"
    gate_src.joinpath("testplan_gate.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("gate_body_test", gate_src / "testplan_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    monkeypatch.setattr(gate, "changed_files", lambda: ["src/stockinsider/agent/repl.py"])
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    import types

    monkeypatch.setattr(gate, "os", types.SimpleNamespace(**{"environ": {"PR_BODY": "", "CI_BASE_SHA": "x"}}))
    try:
        gate.main()
        raise AssertionError("gate must fail on empty PR body in PR context")
    except SystemExit as exc:
        assert "PR_BODY is empty" in str(exc)


# ---- 9. regeneration buffers (streamed only after recheck) ---------------------


def test_regeneration_displays_once_and_only_when_clean(store_fix, prompts_fix) -> None:
    from stockinsider.agent.loop import TurnEngine
    from stockinsider.agent.providers import ChatOutcome
    from stockinsider.agent.repl import build_registry

    from test_streaming import ScriptedProvider

    streamed: list[str] = []
    rendered: list[str] = []

    def sink(piece: str) -> None:
        streamed.append(piece)

    outcomes = [
        ChatOutcome(text="It will surge tomorrow.", usage={}),  # triggers INV-002
        ChatOutcome(text="It might surge (hypothesis).", usage={}),  # clean regen
    ]
    engine = TurnEngine(store_fix, build_registry(store_fix), ScriptedProvider(outcomes), prompts_dir=prompts_fix)
    record = store_fix.create(profile="standard")
    outcome = engine.run_turn(
        record["session_id"],
        "q",
        profile="standard",
        render=rendered.append,
        progress=lambda _l: None,
        stream_sink=sink,
    )
    joined = "".join(streamed)
    # the violating original never streamed; the regen streamed exactly once
    assert "It will surge tomorrow." not in joined
    assert joined.count("It might surge") == 1
    assert outcome.displayed == "It might surge (hypothesis)."


def test_fabricated_regeneration_reaches_screen_only_marked(store_fix, prompts_fix) -> None:
    from stockinsider.agent.loop import TurnEngine
    from stockinsider.agent.providers import ChatOutcome
    from stockinsider.agent.repl import build_registry

    from test_streaming import ScriptedProvider

    streamed: list[str] = []
    rendered: list[str] = []
    outcomes = [
        ChatOutcome(text="It will surge tomorrow.", usage={}),
        ChatOutcome(text="It might surge to 777.77 (hypothesis).", usage={}),  # fabricated number
    ]
    engine = TurnEngine(store_fix, build_registry(store_fix), ScriptedProvider(outcomes), prompts_dir=prompts_fix)
    record = store_fix.create(profile="standard")
    outcome = engine.run_turn(
        record["session_id"],
        "q",
        profile="standard",
        render=rendered.append,
        progress=lambda _l: None,
        stream_sink=streamed.append,
    )
    # TP-023 (ADR-008 requirement change): the regenerated answer is shown
    # once, with the fabricated number marked; the violating original never
    # reaches the screen, and the bare number never does either
    assert outcome.quarantined is False
    assert outcome.unverified == ["777.77"]
    shown = "".join(streamed) + "".join(rendered)
    assert shown.count("777.77[?]") == 1 and shown.count("777.77") == 1
    assert "It will surge tomorrow" not in shown


@pytest.fixture()
def store_fix(tmp_path):
    from stockinsider.agent.session import SessionStore

    return SessionStore(root=tmp_path / "sessions")


@pytest.fixture()
def prompts_fix(tmp_path):

    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "identity.md").write_text(
        "---\nversion: 1\nartifact: identity\n---\n\n# Test identity\n\nYou are a test analyst.\n",
        encoding="utf-8",
    )
    return directory


# ---- 10. prompts v6 -------------------------------------------------------------


def test_identity_prompt_is_v6_with_non_relay_rules() -> None:
    from stockinsider.agent.loop import load_identity_prompt

    version, body = load_identity_prompt()
    assert version == "identity-v6"
    assert "do NOT repeat, spell out, or invent the token" in body
    assert "user_confirmed" not in body


# ---- 11. static arithmetic gate N1 forms ----------------------------------------


def test_static_gate_catches_get_variable_key_and_alias() -> None:
    import sys
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "checks"))
    try:
        from static_arithmetic import scan
    finally:
        sys.path.pop(0)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = root / "src" / "stockinsider" / "agent"
        pkg.mkdir(parents=True)
        (pkg / "_probe.py").write_text(
            "def f(row):\n"
            "    a = row.get('close') + 1\n"
            "    key = 'open'\n"
            "    b = row[key] / 2\n"
            "    v = row['high']\n"
            "    c = v - 1\n"
            "    return a + b + c\n",
            encoding="utf-8",
        )
        violations = scan(root)
        assert len(violations) == 3, violations
