"""Live smoke for the fundamentals endpoint via the vendor's demo token (TP-010).

The demo API token unlocks the demo symbols (AAPL.US et al.) with all
API types — the shape check below runs without the owner's plan or
key. Never blocking.

Implements: REQ-SI-FR-002, REQ-SI-INV-003 (ADR-002)
"""

import json

import pytest

from stockinsider.data.ingest.http import TransportError, stdlib_fetch


def test_fundamentals_demo_shape() -> None:
    try:
        result = stdlib_fetch("https://eodhd.com/api/fundamentals/AAPL.US", {"api_token": "demo", "fmt": "json"})
    except TransportError as exc:
        pytest.skip(f"fundamentals demo endpoint unreachable: {exc}")
    data = json.loads(result.body)
    assert isinstance(data, dict)
    assert "General" in data and "Income_Statement" in data
    quarterly = (data.get("Income_Statement") or {}).get("quarterly") or {}
    assert quarterly, "demo fundamentals expose no quarterly income statements"
    period = sorted(quarterly.keys())[-1]
    assert len(period) == 10
    general = data.get("General") or {}
    assert general.get("Name") == "Apple Inc."
