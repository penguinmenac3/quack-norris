"""Context window management — short-term, mid-term and long-term memory.

The agent loop calls :func:`apply_context_policy` before every LLM call.
Walking backwards from the newest message, history is kept in three tiers:

1. **Verbatim (short-term).**  The newest ``verbatim`` share of the context
   window stays completely intact.
2. **Stripped (mid-term).**  Everything older keeps its user and assistant
   text but has tool outputs replaced by :data:`REDACTION_PLACEHOLDER`.  The
   agent can always re-run the tool if it needs the output again.
3. **Checkpoint (long-term).**  Once utilisation reaches ``checkpoint_at``,
   the oldest messages are summarised into a :class:`CheckpointMessage` until
   utilisation is back under ``target``.

Everything here operates on an in-memory ``list[ChatMessage]``.  This module
knows nothing about sessions, event logs or the filesystem — callers learn
about checkpoints through the returned :class:`CheckpointOutput` and persist
them however they like.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from quack_norris.core.llm import (
    LLM,
    AssistantMessage,
    ChatMessage,
    CheckpointMessage,
    ContextManagementConfig,
    TextDelta,
    Tool,
    ToolResultMessage,
    UserMessage,
)

__all__ = [
    "CHARS_PER_TOKEN",
    "REDACTION_PLACEHOLDER",
    "CheckpointOutput",
    "ContextPolicy",
    "apply_context_policy",
    "checkpoint_content",
    "estimate_tokens",
    "find_safe_cut",
    "measure",
    "message_tokens",
    "strip_old_tool_results",
    "truncate_tool_result",
]

# A crude but stable proxy.  Deliberately not calibrated against reported
# usage — see the note in CLI_STATUS.md; that is a separate piece of work.
CHARS_PER_TOKEN = 4

# Rough per-message wire overhead (role tags, delimiters) in tokens.
_MESSAGE_OVERHEAD = 4

# Tokens held back for the summary that a checkpoint is about to produce,
# since its real size is only known after it has been generated.
_SUMMARY_ALLOWANCE = 512

REDACTION_PLACEHOLDER = (
    "[REDACTED TO SAVE CONTEXT, repeat the operation if the output is needed, "
    "e.g. re-read the file]"
)

_CHECKPOINT_PREFIX = "[Conversation checkpoint — summary of everything so far]: "


_SUMMARISE_SYSTEM = """\
You are a conversation summariser. The user will give you the earliest part of \
an ongoing conversation between a human and an AI coding agent. Produce a \
concise but complete summary that preserves all important context: decisions \
made, code written, file paths touched, tool results that still matter, open \
questions, and the current state of the task. If the input already contains an \
earlier summary, fold it into your output so nothing is lost. Use plain prose. \
Do not include greetings or meta-commentary. The summary replaces those \
messages in the agent's context, so be precise and factual.
"""


# ---------------------------------------------------------------------------
# Policy + results
# ---------------------------------------------------------------------------

@dataclass
class ContextPolicy:
    """Everything :func:`apply_context_policy` needs beyond the conversation.

    ``overflow_sink`` is called with the full text of an oversized tool result
    and returns a location (e.g. a file path) that is mentioned in the
    truncation notice, so the agent knows where to find the rest.  Without a
    sink the notice simply says the output was clipped.
    """

    config: ContextManagementConfig
    context_window: int
    overflow_sink: Callable[[str], str] | None = None


@dataclass
class ContextUsage:
    """Token accounting for one prospective LLM call."""

    total: int
    budget: int
    overhead: int
    per_message: list[int] = field(default_factory=list)

    @property
    def utilisation(self) -> float:
        return self.total / self.budget if self.budget else 0.0


@dataclass
class CheckpointOutput:
    """Emitted when a checkpoint replaces the oldest part of the history."""

    summary: str
    replaced_count: int
    dropped: list[ChatMessage]
    tokens_before: int
    tokens_after: int


def checkpoint_content(summary: str) -> str:
    """Render *summary* the way the model sees it inside a checkpoint message."""
    return _CHECKPOINT_PREFIX + summary


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Approximate the token count of *text*."""
    if not text:
        return 0
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def message_tokens(msg: ChatMessage) -> int:
    """Approximate the token cost of one message, tool-call arguments included."""
    total = estimate_tokens(msg.content or "") + _MESSAGE_OVERHEAD
    if isinstance(msg, AssistantMessage):
        for tc in msg.tool_calls:
            total += estimate_tokens(tc.name)
            try:
                total += estimate_tokens(json.dumps(tc.arguments, ensure_ascii=False))
            except (TypeError, ValueError):
                total += estimate_tokens(str(tc.arguments))
    return total


def tools_tokens(tools: list[Tool]) -> int:
    """Approximate the token cost of the tool schemas sent with every call.

    Recomputed per call on purpose: the tool list changes between turns as
    agents, projects and background processes come and go.
    """
    total = 0
    for t in tools:
        total += estimate_tokens(t.name) + estimate_tokens(t.description)
        try:
            total += estimate_tokens(json.dumps(t.parameters, ensure_ascii=False))
        except (TypeError, ValueError):
            total += estimate_tokens(str(t.parameters))
        total += estimate_tokens(" ".join(t.required))
    return total


def measure(
    history: list[ChatMessage],
    system_prompt: str,
    tools: list[Tool],
    context_window: int,
) -> ContextUsage:
    """Account for everything that will be sent: prompt + tool schemas + history."""
    per_message = [message_tokens(m) for m in history]
    overhead = estimate_tokens(system_prompt) + tools_tokens(tools)
    return ContextUsage(
        total=overhead + sum(per_message),
        budget=max(1, context_window),
        overhead=overhead,
        per_message=per_message,
    )


# ---------------------------------------------------------------------------
# Tier 2 — stripping stale tool output
# ---------------------------------------------------------------------------

def strip_old_tool_results(
    history: list[ChatMessage],
    per_message: list[int],
    verbatim_tokens: int,
) -> int:
    """Redact tool outputs that fall outside the newest ``verbatim_tokens``.

    Mutates *history* and keeps *per_message* in sync.  User and assistant
    text is never touched, and a redacted result is never removed from the
    list — only its content shrinks, so tool-call ids stay matched.

    Returns the number of messages redacted.
    """
    if verbatim_tokens <= 0:
        return 0

    used = 0
    boundary = 0
    for i in range(len(history) - 1, -1, -1):
        used += per_message[i]
        if used > verbatim_tokens:
            boundary = i + 1
            break

    redacted = 0
    for i in range(boundary):
        msg = history[i]
        if isinstance(msg, ToolResultMessage) and msg.content != REDACTION_PLACEHOLDER:
            msg.content = REDACTION_PLACEHOLDER
            per_message[i] = message_tokens(msg)
            redacted += 1
    return redacted


# ---------------------------------------------------------------------------
# Tier 3 — checkpointing
# ---------------------------------------------------------------------------

def _last_safe_index(history: list[ChatMessage]) -> int:
    """Index of the newest message that is a legal cut point."""
    for i in range(len(history) - 1, -1, -1):
        if not isinstance(history[i], ToolResultMessage):
            return i
    return 0


def find_safe_cut(
    history: list[ChatMessage],
    per_message: list[int],
    keep_tokens: int,
) -> int:
    """Return how many leading messages to drop so the rest fits ``keep_tokens``.

    A cut at index ``i`` is legal only when ``history[i]`` is not a
    :class:`ToolResultMessage`: tool results always directly follow the
    assistant message that requested them, so cutting anywhere else would
    orphan a result whose ``tool_call_id`` no longer appears in the history,
    which providers reject outright.

    Cuts are therefore rounded *forward* (dropping a whole assistant +
    tool-results block together), and always leave at least one message.
    """
    if not history:
        return 0

    used = 0
    cut = 0
    for i in range(len(history) - 1, -1, -1):
        if used + per_message[i] > keep_tokens:
            cut = i + 1
            break
        used += per_message[i]

    while cut < len(history) and isinstance(history[cut], ToolResultMessage):
        cut += 1

    return min(cut, _last_safe_index(history))


def _render_transcript(messages: list[ChatMessage]) -> str:
    lines: list[str] = []
    for m in messages:
        if isinstance(m, CheckpointMessage):
            lines.append(f"Summary of even earlier messages: {m.content}")
        elif isinstance(m, UserMessage):
            lines.append(f"User: {m.content}")
        elif isinstance(m, AssistantMessage):
            if m.content:
                lines.append(f"Assistant: {m.content}")
            for tc in m.tool_calls:
                lines.append(f"Assistant called tool: {tc.name} {tc.arguments}")
        elif isinstance(m, ToolResultMessage):
            prefix = "Tool error" if m.is_error else "Tool result"
            lines.append(f"{prefix}: {m.content}")
    return "\n\n".join(lines)


async def _summarise(messages: list[ChatMessage], model: str) -> str:
    transcript = _render_transcript(messages)
    if not transcript.strip():
        return ""
    stream = await LLM.converse(
        model=model,
        system_prompt=_SUMMARISE_SYSTEM,
        tools=[],
        chat_history=[UserMessage(content=transcript)],
    )
    chunks: list[str] = []
    async for item in stream:
        if isinstance(item, TextDelta):
            chunks.append(item.text)
    return "".join(chunks).strip()


# ---------------------------------------------------------------------------
# Per-result cap
# ---------------------------------------------------------------------------

def truncate_tool_result(
    content: str,
    max_tokens: int,
    sink: Callable[[str], str] | None = None,
) -> str:
    """Clip an oversized tool result to ``max_tokens``, keeping head and tail.

    The tail is kept because that is where stack traces, exit codes and error
    summaries live — head-only truncation throws away exactly the part that
    usually matters.  The truncated form is the only form that exists
    downstream: the agent, the renderer and the event log all see this.
    """
    if max_tokens <= 0:
        return content
    limit = max_tokens * CHARS_PER_TOKEN
    if len(content) <= limit:
        return content

    head_len = int(limit * 0.7)
    tail_len = limit - head_len
    removed = len(content) - head_len - tail_len

    location = ""
    if sink is not None:
        try:
            path = sink(content)
        except Exception:  # noqa: BLE001 — a failed sink must not break the turn
            path = ""
        if path:
            location = f" The full output was saved to {path}."

    notice = (
        f"\n\n[tool output clipped: {removed} characters removed because the "
        f"result exceeded the {max_tokens} token limit.{location} Re-run the "
        f"tool in a way that produces less output if you need the rest.]\n\n"
    )
    return content[:head_len] + notice + content[-tail_len:]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def apply_context_policy(
    *,
    history: list[ChatMessage],
    policy: ContextPolicy,
    model: str,
    system_prompt: str,
    tools: list[Tool],
) -> CheckpointOutput | None:
    """Bring *history* back within budget, mutating it in place.

    Strips stale tool output first (cheap, every call), then checkpoints only
    if utilisation is still at or above ``checkpoint_at``, summarising away
    ``checkpoint_reduction_rate`` of the history.

    Returns a :class:`CheckpointOutput` when a checkpoint was created, else
    ``None``.
    """
    cfg = policy.config
    if not cfg.enabled or not history:
        return None

    usage = measure(history, system_prompt, tools, policy.context_window)
    strip_old_tool_results(
        history, usage.per_message, int(usage.budget * cfg.verbatim),
    )
    tokens_before = usage.overhead + sum(usage.per_message)

    if tokens_before < usage.budget * cfg.checkpoint_at:
        return None

    # Drop `checkpoint_reduction_rate` of the *history* (not of the window),
    # leaving room for the summary we are about to put in its place.  Sizing
    # the cut against the history means a checkpoint always removes a
    # predictable share of what is actually there, whatever the window size
    # or how much of it the system prompt and tool schemas take up.
    history_tokens = sum(usage.per_message)
    # The allowance scales with the history: a summary of a small history is
    # itself small, and a flat reserve would swamp the cut and summarise away
    # far more than the configured rate.
    allowance = min(_SUMMARY_ALLOWANCE, history_tokens // 10)
    keep_tokens = (
        int(history_tokens * (1.0 - cfg.checkpoint_reduction_rate)) - allowance
    )
    cut = find_safe_cut(history, usage.per_message, max(keep_tokens, 0))
    if cut <= 0:
        return None

    previous = history[0] if isinstance(history[0], CheckpointMessage) else None
    if cut == 1 and previous is not None:
        return None  # nothing new to fold in — re-summarising a summary is churn

    dropped = history[:cut]
    summary = await _summarise(dropped, cfg.summarizer_model or model)
    if not summary:
        return None

    # `replaced_count` is measured against the raw message list from storage,
    # so a checkpoint that swallows an earlier checkpoint inherits its count.
    replaced_count = cut + (previous.replaced_count - 1 if previous else 0)
    history[:cut] = [
        CheckpointMessage(
            content=checkpoint_content(summary), replaced_count=replaced_count,
        )
    ]

    tokens_after = usage.overhead + sum(message_tokens(m) for m in history)
    return CheckpointOutput(
        summary=summary,
        replaced_count=replaced_count,
        dropped=dropped,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
    )
