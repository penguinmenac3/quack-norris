"""History compaction — shared implementation for /compact and auto-compaction.

The single entry point is :func:`compact_history`.  It:

1. Calls the LLM to summarise the current chat history.
2. Appends a ``history_compacted`` event to ``session.jsonl``.
3. Returns the new in-memory chat history (summary prefix + tail events
   that survive the cutoff).

Both the ``/compact`` slash command and the auto-compaction path in
``_run_turn`` call this function; they only differ in the ``trigger`` label
written to the event.
"""

from __future__ import annotations

from typing import Any

from quack_norris.cli.session import append_event, read_events
from quack_norris.core.llm import (
    LLM,
    AssistantMessage,
    ChatMessage,
    TextDelta,
    ToolResultMessage,
    UserMessage,
)

_SUMMARISE_SYSTEM = """\
You are a conversation summariser. The user will give you a conversation \
history. Produce a concise but complete summary that preserves all important \
context: decisions made, code written, file paths changed, open questions, \
and the current state of the task. Use plain prose. Do not include greetings \
or meta-commentary. The summary will be injected as context into a future LLM \
session, so be precise and factual.
"""

_MIN_MESSAGES = 2
_CHARS_PER_TOKEN = 4


def reconstruct_tail(events: list[dict[str, Any]], cutoff_id: int) -> list[ChatMessage]:
    """Rebuild ``ChatMessage`` turns from events with ``id > cutoff_id``.

    Shared by session resume (``_build_chat_history``) and compaction's tail
    retention below, so both reconstruct history identically.
    """
    from quack_norris.core.llm.tool import ToolCallRequest

    history: list[ChatMessage] = []
    pending_text: str | None = None
    pending_tool_calls: list = []
    tool_results_buffer: list[ToolResultMessage] = []

    for ev in events:
        if ev["id"] <= cutoff_id:
            continue

        t = ev.get("type")
        data = ev.get("data", {})

        if t in ("user_message", "system_hint"):
            if pending_text is not None or pending_tool_calls:
                history.append(AssistantMessage(
                    content=pending_text or "", tool_calls=pending_tool_calls,
                ))
                pending_text = None
                pending_tool_calls = []
            if tool_results_buffer:
                history.extend(tool_results_buffer)
                tool_results_buffer = []
            history.append(UserMessage(content=data.get("text", "")))

        elif t == "content_end":
            pending_text = data.get("text", "")

        elif t == "tool_call_result":
            tc = ToolCallRequest(
                id=data.get("call_id", ""), name=data.get("tool", ""), arguments={},
            )
            pending_tool_calls.append(tc)
            tool_results_buffer.append(ToolResultMessage(
                tool_call_id=data.get("call_id", ""),
                content=data.get("result", ""),
                is_error=data.get("is_error", False),
            ))

    if pending_text is not None or pending_tool_calls:
        history.append(AssistantMessage(content=pending_text or "", tool_calls=pending_tool_calls))
    if tool_results_buffer:
        history.extend(tool_results_buffer)

    return history


def _events_transcript(events: list[dict[str, Any]], upto_id: int) -> str:
    """Render ``user_message``/``content_end`` events up to and including ``upto_id``."""
    lines: list[str] = []
    for ev in events:
        if ev["id"] > upto_id:
            break
        t = ev.get("type")
        data = ev.get("data", {})
        if t == "user_message":
            lines.append(f"User: {data.get('text', '')}")
        elif t == "content_end":
            lines.append(f"Assistant: {data.get('text', '')}")
        # tool results are omitted — the assistant's response already summarises them
    return "\n\n".join(lines)


async def compact_history(
    chat_history: list[ChatMessage],
    model: str,
    session_id: str,
    trigger: str = "manual",
    target_tokens: int | None = None,
) -> list[ChatMessage]:
    """Summarise ``chat_history``, write a ``history_compacted`` event, return new history.

    Returns the original ``chat_history`` unchanged if there is not enough
    history to summarise (fewer than ``_MIN_MESSAGES`` messages).

    Parameters
    ----------
    chat_history:
        Current in-memory chat history.
    model:
        LLM model string (``"group/model-name"``).
    session_id:
        Active session — the ``history_compacted`` event is appended here.
    trigger:
        ``"manual"`` (from ``/compact``) or ``"auto"`` (threshold exceeded).
    target_tokens:
        If given, the most recent events are kept verbatim as an
        un-summarised tail as long as their estimated size stays within this
        token budget (``compaction.target`` fraction of the context window).
        Only the events before that tail are summarised. If omitted, the
        entire history is summarised (no tail) — the previous behaviour.
    """
    if len(chat_history) < _MIN_MESSAGES:
        return chat_history

    events = read_events(session_id)
    if not events:
        return chat_history

    cutoff_id = events[-1]["id"]
    if target_tokens:
        budget_chars = target_tokens * _CHARS_PER_TOKEN
        used = 0
        tail_start_id: int | None = None
        for ev in reversed(events):
            size = len(str(ev.get("data", {})))
            if used + size > budget_chars:
                break
            used += size
            tail_start_id = ev["id"]
        if tail_start_id is not None:
            cutoff_id = tail_start_id - 1

    transcript = _events_transcript(events, cutoff_id)
    if not transcript:
        return chat_history
    summarise_prompt = f"Summarise this conversation:\n\n{transcript}"

    # Collect streamed summary text
    chunks: list[str] = []
    stream = await LLM.converse(
        model=model,
        system_prompt=_SUMMARISE_SYSTEM,
        tools=[],
        chat_history=[UserMessage(content=summarise_prompt)],
    )
    async for item in stream:
        if isinstance(item, TextDelta):
            chunks.append(item.text)

    summary = "".join(chunks).strip()
    if not summary:
        return chat_history

    append_event(session_id, "history_compacted", {
        "cutoff_id": cutoff_id,
        "summary": summary,
        "trigger": trigger,
    })

    # New in-memory history: summary prefix + verbatim tail (events after cutoff)
    new_history: list[ChatMessage] = [
        UserMessage(content=f"[Previous conversation summary]: {summary}"),
        AssistantMessage(content="Understood. I have the context from the previous conversation."),
    ]
    new_history.extend(reconstruct_tail(events, cutoff_id))
    return new_history
