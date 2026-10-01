"""Terminal UI: the opt-in inline front-end of the REPL (ADR-007).

A presentation layer over agent/repl's dispatch: prompt_toolkit reads
input (framed prompt, slash completion, status line, choice prompts),
Rich writes output (activity indicator, Markdown answers under render
fidelity). It adds no verbs and reaches data only through what the
REPL already uses. prompt_toolkit is imported only when the UI starts,
so the plain REPL never depends on it.

Implements: REQ-SI-FR-026 (ADR-007)
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any

from stockinsider.agent.profiles import Profile
from stockinsider.agent.session import SessionStore


class TuiUnavailable(RuntimeError):
    """The terminal UI cannot start here; the message names the reason.

    Raised before any session opens, so the caller can fall back to the
    plain REPL with an explicit notice (INV-003).

    Implements: REQ-SI-FR-026, REQ-SI-INV-003 (ADR-007)
    """


class TuiDependencyMissing(TuiUnavailable):
    """prompt_toolkit is not installed: an installation defect, reported, not bypassed.

    Implements: REQ-SI-FR-026, REQ-SI-INV-003 (ADR-007)
    """


def run_tui(
    store: SessionStore,
    *,
    data_store: Any = None,
    resume: bool = False,
    session_id: str | None = None,
    profile: Profile | str = Profile.standard,
    data_root: str | None = None,
    console: Any = None,
    clock: Callable[[], float] = time.monotonic,
    require_terminal: bool = True,
) -> None:
    """Start (or resume) a session under the terminal UI.

    Every availability check runs before a session opens: a failure
    raises TuiUnavailable (or TuiDependencyMissing) and nothing is
    created. The dependency is checked first - a broken installation is
    reported as such on any terminal. Tests inject a recording console
    and a prompt_toolkit app session with pipe input, and pass
    require_terminal=False.

    Implements: REQ-SI-FR-026, REQ-SI-FR-013, REQ-SI-FR-023 (ADR-007)
    """
    try:
        import prompt_toolkit  # noqa: F401 - availability probe only
    except ImportError as exc:
        raise TuiDependencyMissing(
            f"the terminal UI needs the prompt_toolkit package ({exc}); reinstall the project or use --ui plain"
        ) from exc
    if require_terminal and not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise TuiUnavailable("stdin and stdout must both be an interactive terminal")
    from stockinsider.agent.repl import resume_session, start_new_session
    from stockinsider.agent.tui.adapter import TuiIO

    io = TuiIO.create(console=console, clock=clock)
    io.welcome()
    if resume:
        resume_session(store, session_id, data_root=data_root, data_store=data_store, io=io)
    else:
        start_new_session(store, profile=profile, data_root=data_root, data_store=data_store, io=io)
