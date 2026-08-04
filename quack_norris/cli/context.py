"""Session-log adapter for the core context manager.

:mod:`quack_norris.core.context` owns the policy and knows nothing about
storage.  This module is the other half: it persists checkpoints to
``session.jsonl``, replays the log back into a chat history, and provides the
overflow sink that oversized tool results are written to.

The contract between the two halves is a single integer.  A checkpoint event
records how many messages of the *raw replayed history* it stands in for::

    {"type": "checkpoint", "data": {"summary": "...", "replaces": 42}}

Reconstruction is then just ``[CheckpointMessage(...)] + raw[42:]``.  This
only works while a replay of the log reproduces the in-memory history message
for message, which is why the agent loop reports every assistant message and
every injected nudge rather than only the final text of a turn.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from typing import Any

from quack_norris.cli.session import append_event, overflow_dir, read_events, session_dir
from quack_norris.core.context import (
    CheckpointOutput,
    ContextPolicy,
    apply_context_policy,
    checkpoint_content,
)
from quack_norris.core.llm import (
    LLM,
    AssistantMessage,
    ChatMessage,
    CheckpointMessage,
    ToolResultMessage,
    UserMessage,
)
from quack_norris.core.llm.tool import ToolCallRequest

_log = logging.getLogger(__name__)

_warned_models: set[str] = set()


# ---------------------------------------------------------------------------
# Policy construction
# ---------------------------------------------------------------------------

def make_overflow_sink(session_id: str):
    """Return a sink that spills oversized tool output into the session dir."""

    def _sink(content: str) -> str:
        path = overflow_dir(session_id) / f"{uuid.uuid4().hex[:8]}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", errors="replace")
        return str(path)

    return _sink


def build_context_policy(model: str, session_id: str | None = None) -> ContextPolicy:
    """Assemble the :class:`ContextPolicy` for *model* from the active config."""
    cfg = LLM.context_config()
    window = LLM.get_context_window(model)

    if cfg.enabled and model not in _warned_models:
        _warned_models.add(model)
        verbatim_tokens = int(window * cfg.verbatim)
        if cfg.max_tool_output > verbatim_tokens:
            _log.warning(
                "context_management.max_tool_output (%d tokens) exceeds the "
                "verbatim window (%d tokens) for %s — a single tool result can "
                "still fill the whole short-term memory.",
                cfg.max_tool_output, verbatim_tokens, model,
            )

    return ContextPolicy(
        config=cfg,
        context_window=window,
        overflow_sink=make_overflow_sink(session_id) if session_id else None,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def log_checkpoint(session_id: str, item: CheckpointOutput, trigger: str) -> None:
    """Record a checkpoint so the history can be rebuilt on resume."""
    append_event(session_id, "checkpoint", {
        "summary": item.summary,
        "replaces": item.replaced_count,
        "trigger": trigger,
        "tokens_before": item.tokens_before,
        "tokens_after": item.tokens_after,
    })


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def replay_messages(events: list[dict[str, Any]]) -> list[ChatMessage]:
    """Rebuild the raw chat history from the event log, checkpoints ignored.

    Produces one :class:`AssistantMessage` per logged assistant message, with
    its tool calls attached and its results directly after it — the same shape
    and the same message count the agent loop holds in memory.
    """
    history: list[ChatMessage] = []
    current: AssistantMessage | None = None

    for ev in events:
        t = ev.get("type")
        data = ev.get("data", {})

        if t in ("user_message", "system_hint"):
            current = None
            history.append(UserMessage(content=data.get("text", "")))

        elif t == "content_end":
            current = AssistantMessage(content=data.get("text", ""), tool_calls=[])
            history.append(current)

        elif t == "tool_call_start":
            if current is None:
                current = AssistantMessage(content="", tool_calls=[])
                history.append(current)
            current.tool_calls.append(ToolCallRequest(
                id=data.get("call_id", ""),
                name=data.get("tool", ""),
                arguments=data.get("arguments", {}),
            ))

        elif t == "tool_call_result":
            call_id = data.get("call_id", "")
            # Synthesise an assistant message if the log somehow lacks one, so
            # a result is never left orphaned — providers reject that outright.
            if current is None:
                current = AssistantMessage(content="", tool_calls=[])
                history.append(current)
            if all(tc.id != call_id for tc in current.tool_calls):
                current.tool_calls.append(ToolCallRequest(
                    id=call_id, name=data.get("tool", ""), arguments={},
                ))
            history.append(ToolResultMessage(
                tool_call_id=call_id,
                content=data.get("result", ""),
                is_error=data.get("is_error", False),
            ))

    return history


def build_chat_history(session_id: str) -> list[ChatMessage]:
    """Reconstruct the in-memory chat history for a session.

    Applies the newest checkpoint, which by construction subsumes every
    earlier one — its summary already folded them in.
    """
    events = read_events(session_id)
    if not events:
        return []

    raw = replay_messages(events)

    newest: dict[str, Any] | None = None
    for ev in events:
        if ev.get("type") == "checkpoint" and (
            newest is None or ev["data"]["replaces"] > newest["data"]["replaces"]
        ):
            newest = ev
    if newest is not None:
        replaced = min(int(newest["data"]["replaces"]), len(raw))
        summary = newest["data"].get("summary", "")
        checkpoint = CheckpointMessage(
            content=checkpoint_content(summary), replaced_count=replaced,
        )
        return [checkpoint, *raw[replaced:]]

    return raw


# ---------------------------------------------------------------------------
# Manual /compact
# ---------------------------------------------------------------------------

async def force_checkpoint(
    *,
    chat_history: list[ChatMessage],
    model: str,
    session_id: str,
    system_prompt: str,
    tools: list,
) -> CheckpointOutput | None:
    """Checkpoint now, regardless of current utilisation (the ``/compact`` path).

    Keeps the configured ``checkpoint_reduction_rate`` but drops the
    ``checkpoint_at`` trigger, so the history shrinks by the usual share even
    when there is plenty of room left.
    """
    policy = build_context_policy(model, session_id)
    forced = ContextPolicy(
        config=replace(policy.config, enabled=True, checkpoint_at=0.0),
        context_window=policy.context_window,
        overflow_sink=policy.overflow_sink,
    )
    result = await apply_context_policy(
        history=chat_history,
        policy=forced,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
    )
    if result is not None:
        log_checkpoint(session_id, result, trigger="manual")
    return result
