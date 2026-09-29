"""CLI presentation helpers: UTF-8 safety, ASCII chrome, summaries.

Chrome strings (headers, separators, arrows) are ASCII-only so no
console codepage can mangle them; model data passes through with
errors=replace. Sync reports render compact by default with
per-item detail on --verbose or failure (TP-015 P0).

Implements: REQ-SI-FR-013 (ADR-001)
"""

from __future__ import annotations

import sys
from typing import Any

_CHROME_MAP = str.maketrans(
    {
        "\u2014": "-",  # em dash
        "\u2013": "-",  # en dash
        "\u00b7": "|",  # middle dot
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2192": "->",
        "\u25b2": "^",
        "\u25bc": "v",
    }
)


def init_output() -> None:
    """Force UTF-8 with replacement on the process streams.

    Windows consoles default to a legacy codepage; unmappable
    characters became literal '?'. Reconfigure once at entry so
    output is stable regardless of host locale (TP-015 P0-1).

    Implements: REQ-SI-FR-013 (ADR-001)
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # already detached / closed: pass through
                pass


def chrome(text: str) -> str:
    """Degrade non-ASCII typography to ASCII in CLI chrome strings.

    Implements: REQ-SI-FR-013 (ADR-001)
    """
    return text.translate(_CHROME_MAP)


def sync_summary_line(report: dict[str, Any]) -> str:
    """One-line compact outcome for a sync report (TP-015 P0-5).

    Implements: REQ-SI-FR-001 (ADR-002)
    """
    counts = report["counts"]
    calls = report["calls"]
    parts = [
        f"sync {report['ran_at']}: ok {counts['ok']}",
        f"failed {counts['failed']}",
        f"deferred {counts['deferred']}",
        f"calls {calls['used']}/{calls['cap']} ({calls['remaining']} remaining)",
    ]
    return " | ".join(parts)


def sync_notable_lines(report: dict[str, Any]) -> list[str]:
    """Failure and defer-reason lines that survive --quiet default.

    Failures always render; deferred items render only with
    --verbose (they are expected budget behavior) (TP-015 P0-5).

    Implements: REQ-SI-FR-001, REQ-SI-INV-003 (ADR-002)
    """
    lines = []
    for item in report["results"]:
        if item["status"] == "failed":
            lines.append(
                chrome(f"FAILED {item['symbol']} {item['action']}: {item['detail']}")
            )
    return lines


def sync_verbose_lines(report: dict[str, Any]) -> list[str]:
    """Full per-item detail lines (TP-015 P0-5).

    Implements: REQ-SI-FR-001 (ADR-002)
    """
    lines = []
    for item in report["results"]:
        lines.append(
            chrome(f"{item['status']:8} {item['symbol']:12} {item['action']:11} {item['detail']}")
        )
    return lines


def news_track_lines(report: dict[str, Any]) -> list[str]:
    """News-track outcome lines, both sources (TP-015 P0-5).

    Implements: REQ-SI-FR-006 (ADR-002)
    """
    lines: list[str] = []
    news = report.get("news")
    if not isinstance(news, dict):
        return lines
    for source in ("gdelt", "eodhd"):
        track = news.get(source)
        if track is None:
            continue
        if isinstance(track, dict) and track.get("failed"):
            lines.append(chrome(f"news/{source} FAILED: {track['failed']}"))
            continue
        if not isinstance(track, dict) or "queries" not in track:
            lines.append(chrome(f"news/{source}: no report (unavailable)"))
            continue
        kept = sum(q.get("kept_new", 0) for q in track["queries"])
        dups = sum(q.get("dups", 0) for q in track["queries"])
        quar = sum(q.get("quarantined", 0) for q in track["queries"])
        status = "held" if not track.get("cursor_advanced") else "advanced"
        lines.append(
            chrome(
                f"news/{source} {track['ran_at']}: {len(track['queries'])} queries | "
                f"new {kept} | dup {dups} | quarantined {quar} | cursor {status}"
            )
        )
        for query in track["queries"]:
            detail = query.get("error") or (
                f"new={query.get('kept_new', 0)} dup={query.get('dups', 0)} "
                f"quarantined={query.get('quarantined', 0)}"
            )
            lines.append(chrome(f"{query['status']:8} {query['bucket']:16} {detail}"))
    return lines


def info_lines_chromed(lines: list[str]) -> list[str]:
    """Info snapshot lines, ASCII-degraded for console safety.

    The store renders typographically ('\u2014'); the console never
    sees that byteshape (TP-015 P0-1/P0-4).

    Implements: REQ-SI-FR-005 (ADR-002)
    """
    return [chrome(line) for line in lines]


def day_change_styled(symbol: str, line: str) -> str:
    """Return the day-change line with ANSI color, region-aware.

    HK/CN convention: red = up, green = down. Otherwise green =
    up, red = down. Non-TTY callers get the plain line back.

    Implements: REQ-SI-FR-005 (ADR-001)
    """
    if not line.startswith("day change"):
        return line
    up = ".HK" in symbol or ".CN" in symbol
    red_up = up
    try:
        value = float(line.rsplit(":", 1)[1].replace("%", "").strip())
    except ValueError:
        return line
    if value > 0:
        color = "31" if red_up else "32"
    elif value < 0:
        color = "32" if red_up else "31"
    else:
        return line
    return f"\033[{color}m{line}\033[0m"


def render_error(message: str) -> str:
    """One error channel: rich red panel on a TTY, plain line piped.

    The plain path keeps the exact historical `error: ...` text so
    scripted consumers and tests are unchanged (TP-015 P1-8).

    Implements: REQ-SI-FR-013, REQ-SI-INV-003 (ADR-001)
    """
    if sys.stdout.isatty():
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        console.print(Panel(message, title="error", border_style="red"))
        return ""
    return f"error: {message}"
