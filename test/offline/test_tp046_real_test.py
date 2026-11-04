"""TP-046: defects found by the 2026-11-04 end-to-end test on a copy of the real store.

Embed backlog on a fresh connection (defect 1), `watch add` for US symbols (defect 2), and three
post-check readings (defect 3; ADR-008 Am5). The post-check cases take the live answers' shapes on
the frozen E-015 ledgers; E-013, E-014 and E-015 run as regression only (their own pins).

Implements: REQ-SI-FR-007, REQ-SI-FR-004, REQ-SI-INV-004, REQ-SI-INV-001, REQ-SI-INV-003
(ADR-003, ADR-002, ADR-008 Am5; TP-046)
"""

from __future__ import annotations

import copy

import pytest
from test_ingest_embed import _pseudo, _seed
from test_tp025_stage5_e013 import _specs
from test_tp042_live_false_flags import BYD, PERF
from typer.testing import CliRunner

from stockinsider.agent import guardrail
from stockinsider.cli import app as cli_app
from stockinsider.data.ingest.embed import run_embed
from stockinsider.data.store import open_data_store, vector
from stockinsider.data.store.db import open_db
from stockinsider.data.store.resolver import Resolution
from stockinsider.data.store.vector import VectorUnavailable, pending_count, pending_news

runner = CliRunner()


# -- defect 1: the embed backlog on a fresh connection ---------------------------------


def test_pending_news_with_vectors_returns_only_unembedded(tmp_path) -> None:
    path = tmp_path / "e.sqlite"
    conn = open_db(path)
    _seed(conn, 20)
    assert run_embed(conn, _pseudo, "test-model")["embedded"] == 20
    _seed(conn, 3, start=20)
    conn.close()
    # a new process opens the store without sqlite-vec loaded (the live `embed` run)
    fresh = open_db(path)
    assert [news_id for news_id, _ in pending_news(fresh)] == [21, 22, 23]
    report = run_embed(fresh, _pseudo, "test-model")
    assert report["failed_batches"] == []
    assert report["embedded"] == 3
    assert report["pending_before"] == 3


def test_pending_news_without_vec_table_returns_all(tmp_path) -> None:
    conn = open_db(tmp_path / "e.sqlite")
    _seed(conn, 4)
    assert [news_id for news_id, _ in pending_news(conn)] == [1, 2, 3, 4]
    assert pending_count(conn) == 4


def test_pending_news_extension_unavailable_fails_closed(tmp_path, monkeypatch) -> None:
    path = tmp_path / "e.sqlite"
    conn = open_db(path)
    _seed(conn, 2)
    run_embed(conn, _pseudo, "test-model")
    _seed(conn, 1, start=2)
    conn.close()
    monkeypatch.setattr(vector, "sqlite_vec", None)
    fresh = open_db(path)
    with pytest.raises(VectorUnavailable):
        pending_news(fresh)
    with pytest.raises(VectorUnavailable):
        pending_count(fresh)


def test_pending_count_is_not_capped(tmp_path) -> None:
    conn = open_db(tmp_path / "e.sqlite")
    _seed(conn, 200)
    assert len(pending_news(conn)) == 128  # the batch limit
    assert pending_count(conn) == 200
    assert run_embed(conn, _pseudo, "test-model")["pending_before"] == 200


# -- defect 2: `watch add` for a US symbol ---------------------------------------------


def _store_factory(monkeypatch, tmp_path, search_results: list[Resolution], calls: dict[str, int]):
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(tmp_path / "data"))

    def _open():  # type: ignore[no-untyped-def]
        store = open_data_store()

        def _search(query: str) -> list[Resolution]:
            calls["search"] += 1
            return list(search_results)

        def _verify(canonical: str, adapter=None):  # type: ignore[no-untyped-def]
            calls["verify"] += 1
            return Resolution(
                canonical_symbol=canonical,
                exchange=canonical.rsplit(".", 1)[1],
                official_name=f"{canonical} (name unverified - vendor search does not index this exchange)",
                asset_type="unverified",
            )

        store.resolver.search = _search  # type: ignore[method-assign]
        store.verify_symbol = _verify  # type: ignore[method-assign]
        return store

    monkeypatch.setattr(cli_app, "open_data_store", _open)


def test_watch_add_us_symbol_uses_search_name(tmp_path, monkeypatch) -> None:
    calls = {"search": 0, "verify": 0}
    found = [
        Resolution(canonical_symbol="AAPL.MX", exchange="MX", official_name="Apple Inc."),
        Resolution(canonical_symbol="AAPL.US", exchange="US", official_name="Apple Inc."),
    ]
    _store_factory(monkeypatch, tmp_path, found, calls)
    declined = runner.invoke(cli_app.app, ["watch", "add", "aapl.us"], input="n\n")
    assert "add AAPL.US (Apple Inc.)?" in declined.output  # INV-004: still confirmed
    assert "watchlist unchanged" in declined.output
    result = runner.invoke(cli_app.app, ["watch", "add", "aapl.us"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "added AAPL.US (Apple Inc.)" in result.output
    assert calls["verify"] == 0
    listed = runner.invoke(cli_app.app, ["watch", "list"])
    assert "AAPL.US  Apple Inc." in listed.output


def test_watch_add_us_symbol_without_exact_match_falls_back(tmp_path, monkeypatch) -> None:
    calls = {"search": 0, "verify": 0}
    found = [Resolution(canonical_symbol="AAPL.MX", exchange="MX", official_name="Apple Inc.")]
    _store_factory(monkeypatch, tmp_path, found, calls)
    result = runner.invoke(cli_app.app, ["watch", "add", "AAPL.US"], input="y\n")
    assert result.exit_code == 0, result.output
    assert calls == {"search": 1, "verify": 1}
    assert "AAPL.MX" not in result.output
    assert "name unverified" in result.output


def test_watch_add_hk_symbol_skips_search(tmp_path, monkeypatch) -> None:
    calls = {"search": 0, "verify": 0}
    _store_factory(monkeypatch, tmp_path, [], calls)
    result = runner.invoke(cli_app.app, ["watch", "add", "0700.hk"], input="y\n")
    assert result.exit_code == 0, result.output
    assert calls == {"search": 0, "verify": 1}


# -- defect 3: post-check readings (ADR-008 Am5) ---------------------------------------


def _verdicts(text: str, ledger: dict) -> dict[str, bool]:
    return {claim.raw: claim.verified for claim in guardrail.postcheck_numbers(text, ledger, _specs()).claims}


def _with_search(ledger: dict, symbols: list[str]) -> dict:
    """The ledger plus a `symbol.search "Tencent"` result naming several listings."""
    widened = copy.deepcopy(ledger)
    widened["turn-0001/symbol.search#9"] = [
        {"canonical_symbol": symbol, "exchange": symbol.split(".")[1], "official_name": "Tencent Holdings Ltd"}
        for symbol in symbols
    ]
    return widened


_TABLE = (
    "Tencent against the Hang Seng over the same windows:\n\n"
    "| Window | Tencent | Hang Seng |\n"
    "|---|---|---|\n"
    "| 20 sessions | {t20} | {h20} |\n"
    "| 60 sessions | -6.5788% | 2.3148% |\n"
)


def test_ambiguous_name_resolves_to_data_symbol() -> None:
    ledger = _with_search(PERF, ["0700.HK", "TCEHY.US", "TENCENT80.BK", "NNND.F"])
    good = _verdicts(_TABLE.format(t20="-4.8828%", h20="3.3446%"), ledger)
    assert all(good.values()), good
    # the index's value written in Tencent's column is still flagged
    swapped = _verdicts(_TABLE.format(t20="+3.3446%", h20="-4.8828%"), ledger)
    assert not swapped["3.3446"] and not swapped["-4.8828"], swapped


def test_ambiguous_name_without_unique_data_symbol_stays_dropped() -> None:
    ledger = _with_search(PERF, ["0700.HK", "TCEHY.US"])
    adr = copy.deepcopy(ledger["turn-0001/market.quote#1"])
    adr.update(symbol="TCEHY.US", currency="USD", close=52.9, adjusted_close=52.9)
    ledger["turn-0001/market.quote#8"] = adr
    from stockinsider.agent.guardrail_claims import index_evidence

    assert "Tencent" not in index_evidence(ledger, _specs()).names


def test_range_after_noun_reads_low_high() -> None:
    for text in (
        "BYD closed at 75.07 within a session range of 74.47 to 75.9.",
        "Latest bar: close 75.07 HKD, range 74.47–75.9.",
    ):
        good = _verdicts(text, BYD)
        assert all(good.values()), (text, good)
    assert not _verdicts("BYD closed at 75.07 within a session range of 74.47 to 76.9.", BYD)["76.9"]
    swapped = _verdicts("Latest bar: close 75.07 HKD, range 75.9–74.47.", BYD)
    assert not swapped["75.9"] and not swapped["74.47"]


def test_suspended_hyphen_is_a_count() -> None:
    # the live shape: a drawdown cue earlier in the clause than the suspended counts
    text = "Tencent's drawdown is deeper than the index's over both the 20-, 60- and 250-session windows."
    claims = guardrail.postcheck_numbers(text, PERF, _specs()).claims
    by_raw = {claim.raw: claim for claim in claims}
    assert all(claim.verified for claim in claims), [(c.raw, c.field, c.reason) for c in claims]
    assert by_raw["60"].field != "drawdown" and by_raw["20"].field != "drawdown"
    # a bare number at a drawdown cue is still a drawdown claim
    bare = {c.raw: c for c in guardrail.postcheck_numbers("Its drawdown of 60 is large.", PERF, _specs()).claims}
    assert bare["60"].field == "drawdown" and not bare["60"].verified

