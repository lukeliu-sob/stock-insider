"""TP-043: the weekly digest (FR-016) on seeded week data.

Fit criterion: the digest's numerics all pass the post-check; missing-data sections render
explicit unavailable placeholders rather than being silently omitted.

Implements: REQ-SI-FR-016, REQ-SI-INV-001, REQ-SI-INV-003 (ADR-001, ADR-005 Am5; TP-043)
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stockinsider.agent import digest as digest_module
from stockinsider.agent import guardrail
from stockinsider.agent.digest import CATALYSTS_UNAVAILABLE, EVENTS_UNAVAILABLE, NARRATION_UNCONFIGURED, run_digest
from stockinsider.agent.loop import TurnEngine
from stockinsider.agent.providers import ChatOutcome
from stockinsider.agent.repl import render_session
from stockinsider.agent.session import SessionStore
from stockinsider.cli.app import app
from stockinsider.data import open_data_store
from test_streaming import ScriptedProvider

runner = CliRunner()
END = date(2026, 10, 2)


def _weekdays(n: int) -> list[str]:
    out, day = [], END
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day -= timedelta(days=1)
    return list(reversed(out))


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    env_file = tmp_path / "no-keys.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(env_file))
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("STOCKINSIDER_SESSIONS_ROOT", str(tmp_path / "sessions"))
    for name in ("PROVIDER_API_KEY", "PROVIDER_BASE_URL", "EODHD_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _seed(symbols: dict[str, tuple[str, float | None]], news: dict[str, list[tuple[str, str]]]) -> None:
    """Watchlist symbols with 30 bars each (None: no bars) and dated headlines."""
    store = open_data_store()
    conn = store._conn  # noqa: SLF001
    dates = _weekdays(30)
    with conn:
        for symbol, (name, base) in symbols.items():
            conn.execute(
                "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified,"
                " source, resolved_at) VALUES (?, 'HK', ?, 'stock', '[]', 1, 'test', '2026-09-01T00:00:00+00:00')",
                (symbol, name),
            )
            if base is None:
                continue
            for i, day in enumerate(dates):
                close = round(base + (i % 4) * 1.5 - i * 0.25, 2)
                conn.execute(
                    "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close, adjusted_close,"
                    " volume, currency, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1000, 'HKD', 'test',"
                    " '2026-10-03')",
                    (symbol, day, close, close, close, close, close),
                )
        for symbol, items in news.items():
            for i, (title, published) in enumerate(items):
                conn.execute(
                    "INSERT INTO news (url_norm, url_raw, title, domain, published_at, fetched_at, source_query,"
                    " symbol, relevance_score, kept, sentiment, source) VALUES (?, ?, ?, 'example.com', ?,"
                    " '2026-10-03', 'eodhd', ?, 1.0, 1, ?, 'eodhd')",
                    (f"example.com/{symbol}/{i}", f"https://example.com/{symbol}/{i}", title, published, symbol,
                     json.dumps({"polarity": 0.5, "neg": 0.1, "neu": 0.6, "pos": 0.3})),
                )
    for symbol in symbols:
        store.watchlist.add_verified(symbol, user_confirmed=True, via="cli")
    store.close()


SEEDED = {"0700.HK": ("Tencent Holdings Ltd", 420.0), "1211.HK": ("BYD Company Ltd", 74.0)}
NEWS = {
    "0700.HK": [
        ("Tencent lifts buyback pace after quarterly results", "2026-10-01T09:00:00+00:00"),
        ("Tencent cloud unit signs regional data-centre deal", "2026-08-01T09:00:00+00:00"),
    ]
}


def _run(engine_factory=None):
    lines: list[str] = []
    data_store = open_data_store()
    try:
        outcome = run_digest(SessionStore(), data_store=data_store, echo=lines.append, engine_factory=engine_factory)
    finally:
        data_store.close()
    return outcome, lines


def _without_narration(_store, _registry):
    return None


def _section(text: str, symbol: str) -> str:
    start = text.index(f"## {symbol}")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def test_digest_sections_on_seeded_week(env: Path) -> None:
    _seed(SEEDED, NEWS)
    outcome, _lines = _run(_without_narration)
    assert outcome.symbols == ["0700.HK", "1211.HK"] and outcome.failed == []
    tencent = _section(outcome.text, "0700.HK")
    assert "## 0700.HK — Tencent Holdings Ltd" in tencent
    week = re.search(r"- week \(5 sessions, (\S+) to (\S+)\): adjusted close (\S+) to (\S+), change (\S+)%", tencent)
    assert week is not None, tencent
    snapshots = SessionStore().load_snapshots(outcome.session_id)
    perf = next(v for _turn, values in snapshots for k, v in values.items() if k.endswith("market.performance#2"))
    row = next(r for r in perf["windows"] if r["sessions"] == 5)
    assert week.groups() == (
        row["from_date"], row["to_date"], str(row["from_adjusted_close"]), str(row["adjusted_close"]),
        f"+{row['change_pct']}" if row["change_pct"] > 0 else str(row["change_pct"]),
    )
    assert '"Tencent lifts buyback pace after quarterly results" (2026-10-01)' in tencent
    assert "data-centre deal" not in tencent  # dated outside the week window


def test_digest_numerics_pass_postcheck(env: Path) -> None:
    _seed(SEEDED, NEWS)
    outcome, _lines = _run(_without_narration)
    store = SessionStore()
    specs = {spec.name: spec for spec in digest_module.build_registry(store).list_tools()}
    for (_turn, values), symbol in zip(store.load_snapshots(outcome.session_id), outcome.symbols):
        section = _section(outcome.text, symbol).split("\n- narration:")[0]
        verdict = guardrail.postcheck_numbers(section, values, specs)
        assert verdict.passed, (symbol, verdict.failed)
    assert "[?]" not in outcome.text


def test_missing_sections_are_explicit_placeholders(env: Path) -> None:
    _seed(SEEDED, NEWS)
    outcome, _lines = _run(_without_narration)
    byd = _section(outcome.text, "1211.HK")
    assert "- headlines this week: unavailable: tool 'news.recent' failed: LookupError: 1211.HK: no stored news" in byd
    for section in (byd, _section(outcome.text, "0700.HK")):
        assert f"- scored events: {EVENTS_UNAVAILABLE}" in section
        assert f"- upcoming catalysts: {CATALYSTS_UNAVAILABLE}" in section
        assert f"- narration: {NARRATION_UNCONFIGURED}" in section


def test_symbol_without_bars_fails_visibly(env: Path) -> None:
    _seed({**SEEDED, "9988.HK": ("Alibaba Group Holding Ltd", None)}, NEWS)
    result = runner.invoke(app, ["digest"])
    assert result.exit_code == 1
    alibaba = _section(result.output, "9988.HK")
    no_bars = "tool 'market.quote' failed: LookupError: 9988.HK: no stored market data"
    assert f"- latest bar: unavailable: {no_bars}" in alibaba
    assert "- week: unavailable: tool 'market.performance' failed: LookupError" in alibaba
    assert "## 0700.HK" in result.output  # the other symbols still render


def test_empty_watchlist_is_explicit(env: Path) -> None:
    result = runner.invoke(app, ["digest"])
    assert result.exit_code == 0
    assert "watchlist is empty; nothing to digest" in result.output
    assert SessionStore().list_sessions() == []


def test_digest_is_a_replayable_session(env: Path) -> None:
    _seed(SEEDED, NEWS)
    outcome, _lines = _run(_without_narration)
    store = SessionStore()
    events = store.read_events(outcome.session_id)
    calls = [(e["tool"], e["arguments"]["symbol"]) for e in events if e["event"] == "tool-call"]
    assert calls == [
        (tool, symbol)
        for symbol in ("0700.HK", "1211.HK")
        for tool in ("market.quote", "market.performance", "news.recent")
    ]
    assert len(store.load_snapshots(outcome.session_id)) == 2
    row = store.list_sessions()[0]
    assert row["status"] == "closed" and row["subject_symbols"] == ["0700.HK", "1211.HK"]
    shown: list[str] = []
    render_session(store, outcome.session_id, shown.append)
    assert any(outcome.artifact in line for line in shown)


def test_narration_runs_through_the_engine(env: Path) -> None:
    _seed({"0700.HK": SEEDED["0700.HK"]}, NEWS)
    texts = ["Tencent closed the week at 999.0 HKD; the change is in the table above."]
    provider = ScriptedProvider([ChatOutcome(text=text, usage={}) for text in texts])
    outcome, _lines = _run(lambda store, registry: TurnEngine(store, registry, provider))
    narration = outcome.text.split("- narration: ", 1)[1]
    assert "999.0[?]" in narration  # the wrong number is marked by the engine's post-check
    events = SessionStore().read_events(outcome.session_id)
    assert any(e["event"] == "assistant-message" for e in events)


def test_cli_digest_without_provider(env: Path) -> None:
    _seed(SEEDED, NEWS)
    result = runner.invoke(app, ["digest"])
    assert result.exit_code == 0, result.output
    assert "# Weekly digest" in result.output
    assert NARRATION_UNCONFIGURED in result.output
    assert "digest stored: digest-" in result.output


def test_postcheck_gate_marks_a_bad_deterministic_number(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate is live: a number the snapshot does not hold is marked, never shown as verified."""
    _seed({"0700.HK": SEEDED["0700.HK"]}, NEWS)
    real = digest_module._section

    def tampered(symbol, results):
        lines, priced = real(symbol, results)
        return [*lines, "- prior close: 123.45 HKD"], priced

    monkeypatch.setattr(digest_module, "_section", tampered)
    outcome, _lines = _run(_without_narration)
    assert "123.45[?]" in outcome.text


def test_compact_gdelt_stamps_are_dated_and_filtered(env: Path) -> None:
    """Live stores hold GDELT stamps (20261001T090000Z), not ISO; the first build rendered
    "20261001T0" and let every headline through the week filter."""
    _seed(
        {"0700.HK": SEEDED["0700.HK"]},
        {"0700.HK": [
            ("Oracle lands major cloud deal with Tencent", "20261001T090000Z"),
            ("Tencent stock jumps after new AI model", "20260922T100000Z"),
        ]},
    )
    outcome, _lines = _run(_without_narration)
    tencent = _section(outcome.text, "0700.HK")
    assert '"Oracle lands major cloud deal with Tencent" (2026-10-01)' in tencent
    assert "new AI model" not in tencent  # dated before the week window
    assert "20261001T" not in tencent and "[?]" not in outcome.text
