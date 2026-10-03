"""TP-026: DE-06, cross-file ID reference validity.

Implements: REQ-SI-GOV-002 (DE-06)
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools" / "checks"))
import reference_lint  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _known(**overrides: set[str]) -> dict[str, set[str]]:
    base = {"DE": {"1", "15"}, "TP": {"024", "026"}, "RM": {"62"}, "ADR": {"008"}, "REQ": {"REQ-SI-INV-001"}}
    base.update(overrides)
    return base


def test_reference_lint_catches_a_dangling_id() -> None:
    files = {"fake.md": "see DE-9999 for context, also TP-999 and RM-500 and ADR-999 and REQ-SI-FAKE-001."}
    dangling = reference_lint.find_dangling(files, _known(), tp_bases=set())
    joined = "\n".join(dangling)
    assert "DE-9999" in joined
    assert "TP-999" in joined
    assert "RM-500" in joined
    assert "ADR-999" in joined
    assert "REQ-SI-FAKE-001" in joined
    assert len(dangling) == 5


def test_reference_lint_accepts_known_ids_and_tp_family_members() -> None:
    files = {
        "fake.md": (
            "DE-15 and TP-024 and RM-62 and ADR-008 and REQ-SI-INV-001 are real. "
            "TP-011a and TP-011b cite a plan filed only as TP-011."
        )
    }
    dangling = reference_lint.find_dangling(files, _known(TP={"011", "024", "026"}), tp_bases={"011"})
    assert dangling == []


def test_reference_lint_accepts_the_pinned_forward_reference() -> None:
    files = {"fake.md": "deferred to TP-025, which is not written yet."}
    assert reference_lint.find_dangling(files, _known(), tp_bases=set()) == []


def test_reference_lint_passes_on_the_real_tree() -> None:
    result = subprocess.run(
        [sys.executable, "tools/checks/reference_lint.py"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("PASS reference lint:")
