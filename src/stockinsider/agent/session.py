"""Session lifecycle: append-only persistence, index, values-as-seen snapshots.

Layout per FR-011: sessions/<session_id>/ containing session.jsonl
(append-only event stream), artifacts/ (per-turn reports, never
overwritten), and context/ (per-response snapshots, values-as-seen).
The sessions index is a single-writer table derived from, and validated
against, the session directories.

Implements: REQ-SI-FR-011, REQ-SI-FR-020 (ADR-001)
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stockinsider.agent.profiles import Profile
from stockinsider.shared.provenance import (
    PLACEHOLDER_PREFIX,
    PROVENANCE_FIELDS,
    validate_provenance,
)


class SessionError(RuntimeError):
    """Explicit session-layer failure: never silent, never fabricated.

    Implements: REQ-SI-FR-011 (ADR-001)
    """


def _now() -> str:
    """UTC timestamp, second precision, ISO-8601."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_session_id() -> str:
    """Sortable session id: UTC stamp plus short random suffix."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _provenance_defaults() -> dict[str, str]:
    """Explicit placeholders (shared authority) until resolved values are supplied."""
    return {field: f"{PLACEHOLDER_PREFIX}-supplied-by-creation-context" for field in PROVENANCE_FIELDS}


class SessionStore:
    """Single writer for session trees and the sessions index.

    Implements: REQ-SI-FR-011 (ADR-001)
    """

    def __init__(self, root: Path | str | None = None) -> None:
        """Resolve the sessions root: explicit, then env override, then ./sessions."""
        if root is not None:
            self.root = Path(root)
        else:
            self.root = Path(os.environ.get("STOCKINSIDER_SESSIONS_ROOT", "sessions"))
        self.index_path = self.root / "index.json"

    # -- creation and teardown -------------------------------------------

    def create(
        self,
        profile: Profile | str = Profile.standard,
        subject_symbols: list[str] | None = None,
        provenance: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a session tree and index row; return the record.

        The provenance stamp overwrites the explicit placeholders with
        resolved provider values (GOV-005); unspecified fields keep their
        honest placeholders.

        Implements: REQ-SI-FR-011, REQ-SI-FR-020, REQ-SI-GOV-005 (ADR-001)
        """
        try:
            prof = Profile(profile)
        except ValueError:
            valid = "|".join(p.value for p in Profile)
            raise SessionError(f"unknown analysis profile: {profile!r} (expected {valid})") from None
        session_id = _new_session_id()
        session_dir = self.root / session_id
        (session_dir / "artifacts").mkdir(parents=True)
        (session_dir / "context").mkdir()
        stamp = {**_provenance_defaults(), **(provenance or {})}
        validate_provenance(stamp)
        record: dict[str, Any] = {
            "session_id": session_id,
            "profile": prof.value,
            "status": "active",
            "created": _now(),
            "last_active": _now(),
            "subject_symbols": sorted(set(subject_symbols or [])),
            "provenance": stamp,
        }
        first_line = json.dumps({"event": "session-open", "record": record}) + "\n"
        (session_dir / "session.jsonl").write_text(first_line, encoding="utf-8")
        self._index_append(record)
        return record

    def close(self, session_id: str) -> None:
        """Mark a session closed in the index (tree is immutable history).

        Implements: REQ-SI-FR-011 (ADR-001)
        """
        self._require(session_id)
        self._index_update(session_id, status="closed")

    def resume(self, session_id: str, profile: Profile | str | None = None) -> dict[str, Any]:
        """Reopen a session; explicit error on any profile mismatch.

        Implements: REQ-SI-FR-020 (ADR-001)
        """
        self._require(session_id)
        row = self._index_find(session_id)
        if profile is not None and Profile(profile).value != row["profile"]:
            raise SessionError("profile is fixed for the session lifetime; switching requires a new session (FR-020)")
        self._index_update(session_id, status="active")
        return self._index_find(session_id)

    def read_events(self, session_id: str) -> list[dict[str, Any]]:
        """Replay session.jsonl events in order (read-only history source).

        Implements: REQ-SI-FR-011 (ADR-001)
        """
        session_dir = self._require(session_id)
        events: list[dict[str, Any]] = []
        for line in (session_dir / "session.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    # -- append-only event stream and snapshots ---------------------------

    def append_event(self, session_id: str, event: dict[str, Any]) -> None:
        """Append one JSON line to session.jsonl; prior lines never change.

        Implements: REQ-SI-FR-011 (ADR-001)
        """
        session_dir = self._require(session_id)
        with (session_dir / "session.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")
        self._index_update(session_id, last_active=_now())

    def snapshot(self, session_id: str, turn_id: str, values: dict[str, Any]) -> Path:
        """Write a values-as-seen context snapshot; refuses turn reuse.

        Implements: REQ-SI-FR-011 (ADR-001)
        """
        session_dir = self._require(session_id)
        path = session_dir / "context" / f"{turn_id}.json"
        if path.exists():
            raise SessionError(
                f"snapshot for turn {turn_id!r} already exists: snapshots are values-as-seen and never rewritten"
            )
        path.write_text(json.dumps({"turn_id": turn_id, "values": values}, indent=2) + "\n", encoding="utf-8")
        self._index_update(session_id, last_active=_now())
        return path

    def artifact(self, session_id: str, name: str, content: str) -> Path:
        """Write a per-turn artifact; refuses to overwrite existing artifacts.

        Implements: REQ-SI-FR-011 (ADR-001)
        """
        session_dir = self._require(session_id)
        path = session_dir / "artifacts" / name
        if path.exists():
            raise SessionError(f"artifact {name!r} already exists: artifacts are never overwritten (FR-011)")
        path.write_text(content, encoding="utf-8")
        self._index_update(session_id, last_active=_now())
        return path

    # -- listing ------------------------------------------------------------

    def list_sessions(self, symbol: str | None = None, date: str | None = None) -> list[dict[str, Any]]:
        """List index rows whose session dirs exist (phantom rows skipped).

        Implements: REQ-SI-FR-012 (ADR-001)
        """
        rows = [row for row in self._index_read() if (self.root / row["session_id"]).is_dir()]
        if symbol is not None:
            rows = [row for row in rows if symbol in row["subject_symbols"]]
        if date is not None:
            rows = [row for row in rows if row["created"].startswith(date)]
        return sorted(rows, key=lambda row: row["created"])

    # -- index internals (single writer) ------------------------------------

    def _index_read(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        return list(data.get("sessions", []))

    def _index_write(self, rows: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"sessions": rows}, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.index_path)

    def _index_append(self, record: dict[str, Any]) -> None:
        rows = self._index_read()
        rows.append(record)
        self._index_write(rows)

    def _index_find(self, session_id: str) -> dict[str, Any]:
        for row in self._index_read():
            if row["session_id"] == session_id:
                return row
        raise SessionError(f"index row missing for session {session_id!r}")

    def _index_update(self, session_id: str, **fields: Any) -> None:
        rows = self._index_read()
        for row in rows:
            if row["session_id"] == session_id:
                row.update(fields)
        self._index_write(rows)

    def _require(self, session_id: str) -> Path:
        session_dir = self.root / session_id
        if not session_dir.is_dir():
            raise SessionError(f"unknown session: {session_id!r}")
        return session_dir
