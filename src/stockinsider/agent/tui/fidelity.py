"""Render fidelity: an answer shows as Markdown only if every digit survives.

A Markdown renderer is a display transform. Rich renumbers ordered
lists (`1.` / `5.` shows as 1 and 2), hides link targets and drops HTML
comments, so the screen could show a number the session record does not
hold, or hide one it does. An answer therefore renders as Markdown only
when the multiset of digit sequences in the rendered text equals that of
the verified text; otherwise the literal text is shown (screen ==
record, TP-019). Links render with visible targets.

Implements: REQ-SI-FR-026, REQ-SI-INV-001 (ADR-007)
"""

from __future__ import annotations

import io
import re
from collections import Counter

from rich.console import Console, RenderableType
from rich.markdown import Markdown
from rich.text import Text

_DIGITS = re.compile(r"\d+")

#: Wide enough that wrapping never splits a digit run during the check:
#: the check compares content, not layout.
_CHECK_WIDTH = 2000


def digit_sequences(text: str) -> Counter[str]:
    """The multiset of digit runs in a text.

    Implements: REQ-SI-FR-026, REQ-SI-INV-001 (ADR-007)
    """
    return Counter(_DIGITS.findall(text))


def rendered_text(renderable: RenderableType) -> str:
    """What a renderable shows, as unstyled text.

    Implements: REQ-SI-FR-026 (ADR-007)
    """
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        width=_CHECK_WIDTH,
        color_system=None,
        force_terminal=False,
        legacy_windows=False,
        highlight=False,
    )
    console.print(renderable)
    return buffer.getvalue()


def answer_renderable(text: str) -> tuple[RenderableType, bool]:
    """Markdown when it preserves every digit sequence of the text, else literal text.

    Returns the renderable and whether it is Markdown.

    Implements: REQ-SI-FR-026, REQ-SI-INV-001 (ADR-007)
    """
    markdown = Markdown(text, hyperlinks=False)
    if digit_sequences(rendered_text(markdown)) == digit_sequences(text):
        return markdown, True
    return Text(text), False
