"""TP-016 PR-beta: testplan-gate coverage heuristic (review finding 4)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

GATE_SRC = Path(__file__).resolve().parents[2] / "tools" / "checks" / "testplan_gate.py"


def _load_gate(fake_root: Path):
    spec = importlib.util.spec_from_file_location(
        "gate_under_test", fake_root / "tools" / "checks" / "testplan_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scaffold(tmp_path: Path, tp_name: str, mentions: list[str]):
    fake = tmp_path / "r"
    (fake / "tools" / "checks").mkdir(parents=True, exist_ok=True)
    (fake / "tools" / "checks" / "testplan_gate.py").write_text(GATE_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    plans = fake / "docs" / "test-plans"
    plans.mkdir(parents=True, exist_ok=True)
    body = f"# {tp_name}\n\n- Status: approved (test)\n\n"
    body += "\n".join(f"- touches `{m}`" for m in mentions) + "\n"
    (plans / tp_name).write_text(body, encoding="utf-8")
    return fake


def test_gate_passes_when_tp_mentions_changed_file(tmp_path, monkeypatch) -> None:
    fake = _scaffold(tmp_path, "TP-900.md", ["registry.py", "other.py"])
    gate = _load_gate(fake)
    monkeypatch.setattr(
        gate,
        "changed_files",
        lambda: ["src/stockinsider/agent/registry.py", "docs/review-memo.md"],
    )
    monkeypatch.setattr(gate, "added_memo_headings", lambda: ["### RM-900 - PR #900: test"])
    monkeypatch.setattr(gate, "ROOT", fake)
    body_900 = "Test-Plan: TP-900" + chr(10) + "Review-Memo: appended"
    monkeypatch.setattr(gate.os, "environ", {"PR_BODY": body_900, "CI_BASE_SHA": "x"})
    gate.main()  # must not exit


def test_gate_fails_when_tp_mentions_nothing_changed(tmp_path, monkeypatch) -> None:
    fake = _scaffold(tmp_path, "TP-901.md", ["somethingelse.py"])
    gate = _load_gate(fake)
    monkeypatch.setattr(gate, "changed_files", lambda: ["src/stockinsider/cli/render.py"])
    monkeypatch.setattr(gate, "ROOT", fake)
    monkeypatch.setattr(gate.os, "environ", {"PR_BODY": "Test-Plan: TP-901", "CI_BASE_SHA": "x"})
    try:
        gate.main()
        raise AssertionError("gate must fail")
    except SystemExit as exc:
        assert "mentions none of the changed files" in str(exc)


def test_gate_still_requires_approved_status(tmp_path, monkeypatch) -> None:
    fake = _scaffold(tmp_path, "TP-902.md", ["registry.py"])
    gate = _load_gate(fake)
    plans = fake / "docs" / "test-plans" / "TP-902.md"
    plans.write_text("# TP-902\n\n- Status: draft\n\n- touches `registry.py`\n", encoding="utf-8")
    monkeypatch.setattr(
        gate,
        "changed_files",
        lambda: ["src/stockinsider/agent/registry.py", "docs/review-memo.md"],
    )
    monkeypatch.setattr(gate, "added_memo_headings", lambda: ["### RM-902 - PR #902: test"])
    monkeypatch.setattr(gate, "ROOT", fake)
    body_902 = "Test-Plan: TP-902" + chr(10) + "Review-Memo: appended"
    monkeypatch.setattr(gate.os, "environ", {"PR_BODY": body_902, "CI_BASE_SHA": "x"})
    try:
        gate.main()
        raise AssertionError("gate must fail")
    except SystemExit as exc:
        assert "not approved" in str(exc)


def test_this_pr_satisfies_the_heuristic() -> None:
    """Meta: TP-016 mentions every file this remediation program touches."""
    tp_text = (Path(__file__).resolve().parents[2] / "docs" / "test-plans" / "TP-016.md").read_text(encoding="utf-8")
    assert "testplan_gate" in tp_text
    assert "invariants.md" in tp_text


def test_gate_requires_memo_attestation_on_safety_paths(tmp_path, monkeypatch) -> None:
    """Safety-path diffs without a Review-Memo attestation fail (finding 1)."""
    fake = _scaffold(tmp_path, "TP-903.md", ["registry.py"])
    gate = _load_gate(fake)
    monkeypatch.setattr(
        gate,
        "changed_files",
        lambda: ["src/stockinsider/agent/registry.py", "docs/review-memo.md"],
    )
    monkeypatch.setattr(gate, "ROOT", fake)
    monkeypatch.setattr(gate.os, "environ", {"PR_BODY": "Test-Plan: TP-903", "CI_BASE_SHA": "x"})
    try:
        gate.main()
        raise AssertionError("gate must fail on unattested safety path")
    except SystemExit as exc:
        assert "Review-Memo: appended" in str(exc)


def test_gate_requires_memo_file_in_diff_not_just_attestation(tmp_path, monkeypatch) -> None:
    """N2: an attestation without the memo file riding the diff fails."""
    fake = _scaffold(tmp_path, "TP-904.md", ["registry.py"])
    gate = _load_gate(fake)
    monkeypatch.setattr(gate, "changed_files", lambda: ["src/stockinsider/agent/registry.py"])
    monkeypatch.setattr(gate, "ROOT", fake)
    monkeypatch.setattr(
        gate.os, "environ", {"PR_BODY": "Test-Plan: TP-904" + chr(10) + "Review-Memo: appended", "CI_BASE_SHA": "x"}
    )
    try:
        gate.main()
        raise AssertionError("gate must fail on attestation without diff")
    except SystemExit as exc:
        assert "NOT" in str(exc) and "review-memo.md" in str(exc)


def test_gate_memo_check_runs_before_no_implementation_exit(tmp_path, monkeypatch) -> None:
    """new-7 (TP-018): a prompts-only change set must not slip past the
    memo check via the 'no implementation files' early return."""
    fake = _scaffold(tmp_path, "TP-905.md", ["identity.md"])
    gate = _load_gate(fake)
    monkeypatch.setattr(gate, "changed_files", lambda: ["prompts/identity.md"])
    monkeypatch.setattr(gate, "added_memo_headings", lambda: [])
    monkeypatch.setattr(gate, "ROOT", fake)
    monkeypatch.setattr(
        gate.os, "environ", {"PR_BODY": "Review-Memo: appended", "CI_BASE_SHA": "x"}
    )
    try:
        gate.main()
        raise AssertionError("gate must fail on prompts-only without a real memo entry")
    except SystemExit as exc:
        # Any safety-path failure message is correct here (attestation,
        # file-in-diff, or heading); the point is: the early return must
        # not have waved a prompts-only change set through.
        assert "review-memo" in str(exc)


def test_gate_blank_line_memo_padding_fails(tmp_path, monkeypatch) -> None:
    """new-7 (TP-018): touching docs/review-memo.md without adding an
    entry heading (blank-line padding) fails the safety-path check."""
    fake = _scaffold(tmp_path, "TP-906.md", ["identity.md"])
    gate = _load_gate(fake)
    monkeypatch.setattr(
        gate,
        "changed_files",
        lambda: ["prompts/identity.md", "docs/review-memo.md"],
    )
    monkeypatch.setattr(gate, "added_memo_headings", lambda: [])
    monkeypatch.setattr(gate, "ROOT", fake)
    monkeypatch.setattr(
        gate.os,
        "environ",
        {"PR_BODY": "Review-Memo: appended", "CI_BASE_SHA": "x"},
    )
    try:
        gate.main()
        raise AssertionError("gate must fail on padded memo")
    except SystemExit as exc:
        assert "no" in str(exc) and "RM-" in str(exc) and "heading" in str(exc)
