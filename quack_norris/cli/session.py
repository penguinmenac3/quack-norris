"""Session directory management.

Handles:
- Locating the sessions root (~/.config/quack-norris/sessions/)
- Creating new sessions
- Reading/writing meta.json
- Appending events to session.jsonl
- Listing existing sessions for the session menu
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def sessions_root() -> Path:
    base = Path(os.environ.get("QUACK_NORRIS_HOME", Path.home() / ".config" / "quack-norris"))
    root = base / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def session_dir(session_id: str) -> Path:
    return sessions_root() / session_id


def overflow_dir(session_id: str) -> Path:
    """Dir holding this session's tool-output overflow files (agent-owned scratch)."""
    return session_dir(session_id) / "overflow"


def _meta_path(session_id: str) -> Path:
    return session_dir(session_id) / "meta.json"


def _log_path(session_id: str) -> Path:
    return session_dir(session_id) / "session.jsonl"


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@dataclass
class SessionMeta:
    id: str
    name: str | None = None
    agent: str = "Quack Norris"
    model: str | None = None
    cwd: str = field(default_factory=lambda: str(Path.cwd()))
    status: str = "idle"        # idle | working | blocked | error
    pid: int | None = None
    port: int | None = None
    owner: str | None = None    # terminal | webui | None
    created_at: str = field(default_factory=lambda: _now())
    last_active: str = field(default_factory=lambda: _now())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_meta(meta: SessionMeta) -> None:
    path = _meta_path(meta.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")


def read_meta(session_id: str) -> SessionMeta | None:
    path = _meta_path(session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SessionMeta(**data)
    except Exception:  # noqa: BLE001
        return None


def touch_meta(meta: SessionMeta, *, status: str | None = None) -> None:
    """Update last_active (and optionally status) then rewrite meta.json."""
    meta.last_active = _now()
    if status is not None:
        meta.status = status
    write_meta(meta)


# ---------------------------------------------------------------------------
# Session listing
# ---------------------------------------------------------------------------

def list_sessions(*, include_archived: bool = False) -> list[SessionMeta]:
    """Return all sessions sorted by last_active descending, capped at 50."""
    root = sessions_root()
    dirs = [root]
    if include_archived:
        archived = root / "archived"
        if archived.exists():
            dirs.append(archived)

    sessions: list[SessionMeta] = []
    for d in dirs:
        for meta_file in sorted(d.glob("*/meta.json")):
            meta = read_meta(meta_file.parent.name)
            if meta is not None:
                sessions.append(meta)

    sessions.sort(key=lambda m: m.last_active, reverse=True)
    return sessions[:50]


# ---------------------------------------------------------------------------
# Session creation / resume
# ---------------------------------------------------------------------------

def new_session_id() -> str:
    return str(uuid.uuid4())


def create_session(meta: SessionMeta) -> None:
    """Create session directory and write initial meta.json. No jsonl written yet."""
    session_dir(meta.id).mkdir(parents=True, exist_ok=True)
    write_meta(meta)


def session_exists(session_id: str) -> bool:
    return session_dir(session_id).exists()


def archive_session(session_id: str) -> bool:
    """Move session directory to sessions/archived/<id>/. Returns True on success."""
    src = session_dir(session_id)
    if not src.exists():
        return False
    dest_root = sessions_root() / "archived"
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / session_id
    import shutil
    shutil.move(str(src), str(dest))
    return True


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

def append_event(
    session_id: str,
    event_type: str,
    data: dict[str, Any],
    *,
    min_id: int | None = None,
) -> int:
    """Append one event line to session.jsonl. Returns the assigned event id.

    ``min_id`` enforces a lower bound on the assigned id.  Pass the value
    returned by :func:`remove_streaming_events` when removing events before
    appending, so the new id is always strictly greater than any removed one.
    """
    path = _log_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    event_id = _next_event_id(path)
    if min_id is not None and event_id <= min_id:
        event_id = min_id + 1

    event = {
        "id": event_id,
        "type": event_type,
        "ts": _now(),
        "data": data,
    }
    with path.open("a", encoding="utf-8", errors="surrogatepass") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event_id


def _next_event_id(path: Path) -> int:
    """Return the next event id by reading the last event's id field."""
    if not path.exists():
        return 0
    last_id = -1
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    ev = json.loads(line)
                    eid = ev.get("id")
                    if isinstance(eid, int) and eid > last_id:
                        last_id = eid
                except json.JSONDecodeError:
                    continue
    return last_id + 1


def read_events(session_id: str) -> list[dict[str, Any]]:
    """Read all events from session.jsonl, skipping blank lines."""
    path = _log_path(session_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def remove_streaming_events(session_id: str, message_id: str) -> int:
    """Remove content_start and content_delta lines for a given message_id.

    Returns the highest event id seen across *all* lines (including removed
    ones) so the caller can pass it as ``min_id`` to :func:`append_event`,
    ensuring the next id is strictly greater than any removed id.
    """
    path = _log_path(session_id)
    if not path.exists():
        return -1
    lines: list[str] = []
    max_id = -1
    with path.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                try:
                    ev = json.loads(stripped)
                    eid = ev.get("id")
                    if isinstance(eid, int) and eid > max_id:
                        max_id = eid
                    if ev.get("type") in ("content_start", "content_delta") and \
                       ev.get("data", {}).get("message_id") == message_id:
                        continue  # drop the line entirely
                except json.JSONDecodeError:
                    pass
            lines.append(line)
    path.write_text("".join(lines), encoding="utf-8")
    return max_id
