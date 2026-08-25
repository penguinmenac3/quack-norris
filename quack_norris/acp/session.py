from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    AvailableCommandsUpdate,
    ConfigOptionUpdate,
    CurrentModeUpdate,
    SessionInfo,
    SessionInfoUpdate,
    ToolCallProgress,
    ToolCallStart,
    UserMessageChunk,
)
from pydantic import TypeAdapter

from quack_norris.core import ContextPolicy, SkillInfo
from quack_norris.core.llm import (
    AssistantMessage,
    ChatMessage,
    CheckpointMessage,
    ToolCallRequest,
    ToolResultMessage,
    UserMessage,
)

ACPUpdate = (
    UserMessageChunk
    | AgentMessageChunk
    | AgentThoughtChunk
    | ToolCallStart
    | ToolCallProgress
    | AvailableCommandsUpdate
    | CurrentModeUpdate
    | ConfigOptionUpdate
    | SessionInfoUpdate
)
_SESSION_UPDATE_ADAPTER = TypeAdapter(ACPUpdate)
_SESSION_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sessions_root() -> Path:
    home = Path(os.environ.get("QUACK_NORRIS_HOME", Path.home() / ".config" / "quack-norris"))
    root = home / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_directory(session_id: str) -> Path:
    if _SESSION_ID_PATTERN.fullmatch(session_id) is None:
        raise ValueError("Invalid session ID")
    root = sessions_root().resolve()
    directory = (root / session_id).resolve()
    if directory.parent != root:
        raise ValueError("Invalid session ID")
    return directory


@dataclass
class ACPSession:
    session_id: str
    cwd: Path
    model: str
    system_prompt: str
    selected_agent: str = "Quack Norris"
    title: str | None = None
    additional_directories: tuple[Path, ...] = ()
    skills: list[SkillInfo] = field(default_factory=list)
    tools: list[Any] = field(default_factory=list)
    chat_history: list[ChatMessage] = field(default_factory=list)
    context_policy: ContextPolicy | None = None
    operation_registry: Any = None
    active_prompt: Any = None
    prompt_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cancelled: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class SessionStore:
    def create(
        self,
        *,
        cwd: Path,
        model: str,
        system_prompt: str,
        additional_directories: list[str] | None = None,
    ) -> ACPSession:
        resolved_additional: list[Path] = []
        for raw_path in additional_directories or []:
            path = Path(raw_path)
            if not path.is_absolute() or not path.exists() or not path.is_dir():
                raise ValueError("Additional directories must be existing absolute directories")
            resolved_additional.append(path.resolve())
        session = ACPSession(
            session_id=uuid.uuid4().hex,
            cwd=cwd.resolve(),
            model=model,
            system_prompt=system_prompt,
            additional_directories=tuple(resolved_additional),
        )
        self.save(session)
        return session

    def save(self, session: ACPSession) -> None:
        session.updated_at = _now()
        directory = _session_directory(session.session_id)
        directory.mkdir(parents=True, exist_ok=True)
        metadata = {
            "schema_version": 1,
            "session_id": session.session_id,
            "cwd": str(session.cwd),
            "additional_directories": [str(path) for path in session.additional_directories],
            "model": session.model,
            "selected_agent": session.selected_agent,
            "system_prompt": session.system_prompt,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }
        self._atomic_write(directory / "meta.json", metadata)
        self._atomic_write(
            directory / "history.json",
            [_serialize_message(message) for message in session.chat_history],
        )

    def load(self, session_id: str) -> ACPSession | None:
        try:
            directory = _session_directory(session_id)
        except ValueError:
            return None
        metadata_path = directory / "meta.json"
        if not metadata_path.exists():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("session_id") != session_id:
                return None
            history_path = directory / "history.json"
            history_data = (
                json.loads(history_path.read_text(encoding="utf-8"))
                if history_path.exists()
                else []
            )
            return ACPSession(
                session_id=metadata["session_id"],
                cwd=Path(metadata["cwd"]),
                model=metadata["model"],
                system_prompt=metadata["system_prompt"],
                selected_agent=metadata.get("selected_agent", "Quack Norris"),
                title=metadata.get("title"),
                additional_directories=tuple(
                    Path(path) for path in metadata.get("additional_directories", [])
                ),
                chat_history=[_deserialize_message(message) for message in history_data],
                created_at=metadata.get("created_at", _now()),
                updated_at=metadata.get("updated_at", _now()),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def list_sessions(self, cwd: str | None = None) -> list[SessionInfo]:
        expected_cwd = Path(cwd).resolve() if cwd else None
        sessions: list[SessionInfo] = []
        for metadata_path in sessions_root().glob("*/meta.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                session_id = metadata["session_id"]
                if session_id != metadata_path.parent.name:
                    continue
                _session_directory(session_id)
                session_cwd = Path(metadata["cwd"]).resolve()
                if expected_cwd is not None and session_cwd != expected_cwd:
                    continue
                sessions.append(
                    SessionInfo(
                        session_id=metadata["session_id"],
                        cwd=str(session_cwd),
                        additional_directories=metadata.get("additional_directories") or None,
                        title=metadata.get("title"),
                        updated_at=metadata.get("updated_at"),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        sessions.sort(key=lambda item: item.updated_at or "", reverse=True)
        return sessions

    def append_update(self, session_id: str, update: ACPUpdate) -> None:
        path = _session_directory(session_id) / "updates.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = update.model_dump(mode="json", by_alias=True, exclude_none=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read_updates(self, session_id: str) -> list[ACPUpdate]:
        try:
            path = _session_directory(session_id) / "updates.jsonl"
        except ValueError:
            return []
        if not path.exists():
            return []
        updates: list[ACPUpdate] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                updates.append(_SESSION_UPDATE_ADAPTER.validate_python(json.loads(line)))
            except (ValueError, json.JSONDecodeError):
                continue
        return updates

    @staticmethod
    def _atomic_write(path: Path, payload: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)


def _serialize_message(message: ChatMessage) -> dict[str, Any]:
    if isinstance(message, CheckpointMessage):
        return {
            "type": "checkpoint",
            "content": message.content,
            "replaced_count": message.replaced_count,
        }
    if isinstance(message, UserMessage):
        return {"type": "user", "content": message.content}
    if isinstance(message, AssistantMessage):
        return {
            "type": "assistant",
            "content": message.content,
            "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in message.tool_calls
            ],
        }
    return {
        "type": "tool",
        "tool_call_id": message.tool_call_id,
        "content": message.content,
        "is_error": message.is_error,
    }


def _deserialize_message(payload: dict[str, Any]) -> ChatMessage:
    message_type = payload["type"]
    if message_type == "checkpoint":
        return CheckpointMessage(
            content=payload["content"],
            replaced_count=int(payload.get("replaced_count", 0)),
        )
    if message_type == "user":
        return UserMessage(content=payload["content"])
    if message_type == "assistant":
        return AssistantMessage(
            content=payload["content"],
            tool_calls=[
                ToolCallRequest(
                    id=call["id"],
                    name=call["name"],
                    arguments=call.get("arguments", {}),
                )
                for call in payload.get("tool_calls", [])
            ],
        )
    if message_type == "tool":
        return ToolResultMessage(
            tool_call_id=payload["tool_call_id"],
            content=payload["content"],
            is_error=bool(payload.get("is_error", False)),
        )
    raise ValueError(f"Unknown message type: {message_type}")
