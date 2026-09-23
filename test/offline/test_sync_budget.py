"""Offline tests for the free-tier call budget (TP-009).

Boundary pair (20 ok / 21st refused), lazy daily reset, exhaustion
deferral reporting, the ADR-002 402 single-shot policy, and the
EODHD_DAILY_CALLS override.

Implements: REQ-SI-INV-003 (ADR-002)
"""

import pytest

from stockinsider.data import open_data_store
from stockinsider.data.ingest.budget import DEFAULT_DAILY_CALLS, CallBudget, daily_cap
from stockinsider.data.ingest.http import FetchResult, TransportError
from stockinsider.data.ingest.sync import SyncService


class RateLimitedTransport:
    """Always 402 — the plan-exhausted signal."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, url: str, params: dict[str, str]) -> FetchResult:
        self.calls += 1
        raise TransportError("rate-limited", "EODHD daily call limit reached (HTTP 402)")


@pytest.fixture()
def store(tmp_path):
    ds = open_data_store(tmp_path / "data")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("EODHD_DAILY_CALLS", raising=False)
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(tmp_path / "none.env"))
    yield ds
    monkeypatch.undo()
    ds.close()


def test_cap_20_and_21st_refused(store) -> None:
    budget = CallBudget(store._conn)  # noqa: SLF001
    assert daily_cap() == DEFAULT_DAILY_CALLS == 20
    for _ in range(20):
        assert budget.try_spend(1) is True
    assert budget.try_spend(1) is False
    assert budget.remaining() == 0


def test_lazy_reset_on_date_change(store) -> None:
    conn = store._conn  # noqa: SLF001
    with conn:
        conn.execute(
            "INSERT INTO sync_state (track, calls_today, calls_date) VALUES ('eodhd-budget', 20, '2001-01-01')"
        )
    assert CallBudget(conn).used_today() == 0  # stale date reads as zero


def test_exhaustion_reports_deferred_items(store, monkeypatch) -> None:
    monkeypatch.setenv("EODHD_DAILY_CALLS", "1")
    conn = store._conn  # noqa: SLF001
    service = SyncService(conn, transport=RateLimitedTransport(), news_enabled=False)
    report = service.run()
    assert report.calls_used == 1
    deferred = [i for i in report.results if i.status == "deferred"]
    assert deferred, "budget exhaustion must surface deferred items explicitly"
    assert all("budget" in i.detail for i in deferred)


def test_402_capacity_is_bought_no_retry(store) -> None:
    conn = store._conn  # noqa: SLF001
    transport = RateLimitedTransport()
    report = SyncService(conn, transport=transport, news_enabled=False).run()
    attempted = [i for i in report.results if i.action == "backfill"]
    assert attempted and all(i.status == "failed" for i in attempted)
    assert all("limit" in i.detail for i in attempted)
    assert transport.calls == len(attempted)  # exactly one call per item, zero retries


def test_env_override_changes_cap(store, monkeypatch) -> None:
    monkeypatch.setenv("EODHD_DAILY_CALLS", "5")
    assert daily_cap() == 5
    budget = CallBudget(store._conn)  # noqa: SLF001
    for _ in range(5):
        assert budget.try_spend(1)
    assert not budget.try_spend(1)
