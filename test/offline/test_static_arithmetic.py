"""TP-016 PR-delta: static arithmetic gate self-tests (finding 3).

Implements: REQ-SI-FR-006 (ADR-002; TP-016 PR-delta)
"""

from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "checks"))

from static_arithmetic import scan  # noqa: E402


def _tree(tmp_path: Path, rel: str, body: str) -> Path:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return tmp_path


def test_violation_flagged_outside_compute(tmp_path) -> None:
    root = _tree(
        tmp_path,
        "src/stockinsider/agent/evil.py",
        "def f(close, x):\n    return close * x\n",
    )
    violations = scan(root)
    assert len(violations) == 1
    assert "close" in violations[0] and "evil.py" in violations[0]


def test_same_arithmetic_allowed_inside_compute(tmp_path) -> None:
    root = _tree(
        tmp_path,
        "src/stockinsider/data/compute/ok.py",
        "def f(close, x):\n    return close * x\n",
    )
    assert scan(root) == []


def test_non_market_arithmetic_allowed(tmp_path) -> None:
    root = _tree(
        tmp_path,
        "src/stockinsider/agent/fine.py",
        "def f(count):\n    return count + 1\n",
    )
    assert scan(root) == []


def test_compute_call_and_comparison_allowed(tmp_path) -> None:
    root = _tree(
        tmp_path,
        "src/stockinsider/agent/fine2.py",
        "from stockinsider.data.compute.x import pct\n\n\ndef f(row):\n    v = pct(1, 2)\n    return v > 0\n",
    )
    assert scan(root) == []


def test_real_repo_tree_clean() -> None:
    root = Path(__file__).resolve().parents[2]
    assert scan(root) == []
