"""TP-038: the vendor transport re-checks egress on every redirect (DE-18).

A fake HTTPS handler sits inside the real urllib opener, so urllib's own redirect
machinery runs and calls the egress-checked handler; no socket is opened.

Implements: REQ-SI-SEC-003, REQ-SI-INV-003 (ADR-002, ADR-004; TP-038)
"""

from __future__ import annotations

import email.message
import io
import urllib.request
import urllib.response

import pytest

from stockinsider.data.ingest import http
from stockinsider.data.ingest.http import TransportError, stdlib_fetch
from stockinsider.shared.egress import EgressViolationError

START = "https://eodhd.com/api/eod/0700.HK"


class _FakeHttps(urllib.request.BaseHandler):
    handler_order = 100  # before the real HTTPSHandler, which must never run

    def __init__(self, routes: dict[str, tuple[int, str]], opened: list[str]) -> None:
        self.routes = routes
        self.opened = opened

    def https_open(self, req):  # type: ignore[no-untyped-def]
        url = req.full_url
        self.opened.append(url)
        code, payload = self.routes[url.split("?")[0]]
        headers = email.message.Message()
        if code in (301, 302, 303, 307, 308):
            headers["Location"] = payload
            payload = ""
        response = urllib.response.addinfourl(io.BytesIO(payload.encode("utf-8")), headers, url, code)
        response.msg = "fake"
        return response

    http_open = https_open


@pytest.fixture()
def routes(monkeypatch):
    table: dict[str, tuple[int, str]] = {}
    opened: list[str] = []
    built: list[tuple] = []
    real = urllib.request.build_opener

    def build(*handlers):  # type: ignore[no-untyped-def]
        built.append(handlers)
        return real(*handlers, _FakeHttps(table, opened))

    monkeypatch.setattr(urllib.request, "build_opener", build)
    return table, opened, built


def test_vendor_fetch_uses_the_egress_checked_opener(routes) -> None:
    table, _opened, built = routes
    table[START] = (200, "[]")
    assert stdlib_fetch(START, {"fmt": "json"}).body == "[]"
    assert built and http._EgressCheckedRedirects in built[0]


def test_redirect_off_the_whitelist_becomes_transport_egress(routes) -> None:
    table, opened, _built = routes
    table[START] = (302, "https://evil.example.com/steal")
    table["https://evil.example.com/steal"] = (200, "stolen")
    with pytest.raises(TransportError) as caught:
        stdlib_fetch(START, {"fmt": "json"})
    assert caught.value.kind == "egress"
    assert "evil.example.com" in str(caught.value)
    assert all("evil.example.com" not in url for url in opened)


def test_redirect_to_plain_http_is_refused(routes) -> None:
    table, opened, _built = routes
    table[START] = (301, "http://eodhd.com/api/eod/0700.HK")
    with pytest.raises(TransportError) as caught:
        stdlib_fetch(START, {"fmt": "json"})
    assert caught.value.kind == "egress"
    assert all(not url.startswith("http://") for url in opened)


def test_redirect_within_the_whitelist_is_followed(routes) -> None:
    table, opened, _built = routes
    table[START] = (302, "https://eodhd.com/api/eod/0700.HK.v2")
    table["https://eodhd.com/api/eod/0700.HK.v2"] = (200, '[{"date": "2026-10-23"}]')
    assert stdlib_fetch(START, {"fmt": "json"}).body == '[{"date": "2026-10-23"}]'
    assert opened[-1] == "https://eodhd.com/api/eod/0700.HK.v2"


def test_first_url_violation_still_raises_before_any_request(routes) -> None:
    _table, opened, built = routes
    with pytest.raises(EgressViolationError):
        stdlib_fetch("https://evil.example.com/api", {})
    assert built == [] and opened == []


def test_market_sync_reports_an_egress_item_and_continues(tmp_path, monkeypatch) -> None:
    from test_cli_info import _bars_body

    from stockinsider.data.ingest.http import FetchResult
    from stockinsider.data.ingest.market import EodhdMarketAdapter
    from stockinsider.data.ingest.sync import SyncService
    from stockinsider.data.store.db import open_db

    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("EODHD_DAILY_CALLS", "100")
    conn = open_db(tmp_path / "sync.sqlite")
    with conn:
        for symbol in ("0700.HK", "1211.HK"):
            conn.execute(
                "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified,"
                " source, resolved_at) VALUES (?, 'HK', ?, 'stock', '[]', 1, 'eodhd', '2026-10-01T00:00:00+00:00')",
                (symbol, symbol),
            )
            conn.execute(
                "INSERT INTO watchlist (canonical_symbol, added_at, added_via) VALUES (?, '2026-10-01', 'cli')",
                (symbol,),
            )

    def transport(url: str, params: dict[str, str]) -> FetchResult:
        if "1211.HK" in url:
            raise TransportError("egress", "redirect from eodhd.com refused: host 'evil.example.com' not allowed")
        return FetchResult(200, _bars_body(["2026-10-22", "2026-10-23"]))

    service = SyncService(conn, adapter=EodhdMarketAdapter(transport=transport, api_key="k"), news_enabled=False)
    report = service.run().as_dict()
    by_symbol = {item["symbol"]: item for item in report["results"] if item["action"] == "backfill"}
    assert by_symbol["1211.HK"]["status"] == "failed"
    assert "[egress]" in by_symbol["1211.HK"]["detail"]
    assert by_symbol["0700.HK"]["status"] == "ok"
    conn.close()
