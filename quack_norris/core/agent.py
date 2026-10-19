"""
Core agent loop.

This module is intentionally free of:
- event buses
- HTTP / SSE
- storage
- any framework

It only needs the LLM layer and a list of Tool instances.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from quack_norris.core.context import (
    CheckpointOutput,
    ContextPolicy,
    apply_context_policy,
    truncate_tool_result,
)
from quack_norris.core.llm import (
    LLM,
    ApprovalState,
    AssistantMessage,
    ChatMessage,
    LLMAPIError,
    TextDelta,
    ThinkingDelta,
    Tool,
    ToolCallRequest,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)

__all__ = [
    "agent",
    "AgentOutput",
    "CheckpointOutput",
    "ContextPolicy",
    "ErrorOutput",
    "MessageEnd",
    "NudgeOutput",
    "SkillInfo",
    "TextOutput",
    "ThinkingOutput",
    "ToolCallOutput",
    "ToolResultOutput",
]

# ---------------------------------------------------------------------------
# Agent output types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str


@dataclass
class TextOutput:
    """A streamed chunk of assistant text."""

    text: str


@dataclass
class ThinkingOutput:
    """A streamed chunk of model reasoning."""

    text: str


@dataclass
class ToolCallOutput:
    """The agent is about to call a tool (before execution)."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    needs_approval: ApprovalState


@dataclass
class ToolResultOutput:
    """Result after a tool has been executed (or denied)."""

    tool_call_id: str
    tool_name: str
    result: ToolResult
    show_output: bool = False  # Mirror of Tool.show_output — renderer prints content if True


@dataclass
class MessageEnd:
    """One assistant message is complete (one iteration of the loop).

    Emitted for every assistant message, not just the last one of a turn, so
    that a listener persisting the conversation can record each of them.  A
    replay of those records then reproduces the in-memory history message for
    message, which is what makes checkpoint ``replaced_count`` meaningful.
    """

    text: str
    tool_call_ids: list[str]


@dataclass
class NudgeOutput:
    """A synthetic user message the loop injected (e.g. after an empty reply).

    Also emitted for persistence: it is a real message in the history and
    would otherwise make a replay drift out of sync by one.
    """

    text: str


@dataclass
class ErrorOutput:
    """An LLM provider call failed (rate limit, bad route, connection drop, ...).

    Emitted instead of letting the exception crash the process, so the CLI
    can show the user a clear message and let them take action (e.g. switch
    models with ``/model``) instead of the turn dying with a raw traceback.
    """

    message: str
    retryable: bool = False


AgentOutput = (
    TextOutput
    | ThinkingOutput
    | ToolCallOutput
    | ToolResultOutput
    | MessageEnd
    | NudgeOutput
    | CheckpointOutput
    | ErrorOutput
)

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

_MAX_ITERATIONS = 64
_INTERRUPTED = "---interrupted---"
_EMPTY_RESPONSE_NUDGE = "Your last response was empty. Please try again."


def _format_llm_error(exc: LLMAPIError) -> str:
    """Build a user-facing message for an :class:`LLMAPIError`, with next steps."""
    hint = (
        "This looks temporary — you can wait a moment and try again, "
        if exc.retryable
        else ""
    )
    return f"{exc.message}\n{hint}or select another configured model."


def _append_skill_catalog(system_prompt: str, skills: list[SkillInfo] | None) -> str:
    if not skills:
        return system_prompt
    normalized = [
        SkillInfo(
            name=" ".join(skill.name.split()),
            description=" ".join(skill.description.split()),
        )
        for skill in skills
    ]
    entries = "\n".join(
        f"- {skill.name}: {skill.description}"
        for skill in sorted(normalized, key=lambda item: (item.name.casefold(), item.name))
    )
    return (
        f"{system_prompt.rstrip()}\n\n## Available Skills\n\n{entries}\n\n"
        "Load a relevant skill with the skill invocation tool before following it."
    )


async def agent(
    *,
    model: str,
    system_prompt: str | Callable[[], str],
    tools: list[Tool],
    chat_history: list[ChatMessage],
    on_permission_request: Callable[[ToolCallOutput], Awaitable[bool | ToolResult]],
    on_output: Callable[[AgentOutput], Awaitable[None]],
    context: ContextPolicy | None = None,
    skills: list[SkillInfo] | None = None,
) -> str:
    """
    Run the agent loop until the LLM produces a final text response.

    Parameters
    ----------
    model:
        Model string, e.g. ``"ollama/qwen3:14b"``.
    system_prompt:
        The agent's persona / instructions.
    tools:
        Tool instances the agent may call.  Passed directly to
        :meth:`LLM.converse`; tool definitions are derived automatically and
        each yielded :class:`~quack_norris.core.llm.tool.ToolCallRequest`
        arrives with ``execute`` and ``needs_approval`` already bound.
    chat_history:
        Prior turns (mutable — the loop appends to this list).
    on_permission_request:
        Called when a tool needs human approval (``needs_approval=True`` or
        ``"human"``).  Receives the :class:`ToolCallOutput` for display;
        return ``True`` to allow, ``False`` to deny, or a ``ToolResult`` with
        a denial reason.  When ``needs_approval`` is ``"human"`` the
        whitelist is skipped and this is called directly.
    on_output:
        Called for every :class:`AgentOutput` item as it arrives.
    context:
        Context window management policy. When given, old tool output is
        replaced at new-turn boundaries and, within a turn, when utilisation
        reaches 90% of the checkpoint trigger. The oldest messages are
        summarised only if usage remains above that trigger; oversized tool
        results are also clipped. When ``None`` the history grows unbounded.
    skills:
        Optional compact skill metadata appended to the system prompt.  Full
        instructions remain available through a caller-supplied skill tool.

    Returns
    -------
    str
        The final assistant message (complete text, not streamed).
    """
    history = chat_history
    if isinstance(system_prompt, str):
        def _get_prompt() -> str:
            return _append_skill_catalog(system_prompt, skills)
    else:
        def _get_prompt() -> str:
            return _append_skill_catalog(system_prompt(), skills)

    new_turn = True
    for _iteration in range(_MAX_ITERATIONS):
        # ------------------------------------------------------------------ #
        # Keep the context within budget before spending it                    #
        # ------------------------------------------------------------------ #
        if context is not None:
            checkpoint = await apply_context_policy(
                history=history,
                policy=context,
                model=model,
                system_prompt=_get_prompt(),
                tools=tools,
                new_turn=new_turn,
            )
            if checkpoint is not None:
                await on_output(checkpoint)

        # ------------------------------------------------------------------ #
        # Call the LLM                                                         #
        # ------------------------------------------------------------------ #
        stream = await LLM.converse(
            model=model,
            system_prompt=_get_prompt(),
            tools=tools,
            chat_history=history,
        )
        new_turn = False

        text_chunks: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        try:
            async for item in stream:
                if isinstance(item, ThinkingDelta):
                    await on_output(ThinkingOutput(text=item.text))
                elif isinstance(item, TextDelta):
                    text_chunks.append(item.text)
                    await on_output(TextOutput(text=item.text))
                elif isinstance(item, ToolCallRequest):
                    tool_calls.append(item)
        except asyncio.CancelledError:
            suffix = f"\n\n{_INTERRUPTED}"
            await on_output(TextOutput(text=suffix))
            full_text = "".join(text_chunks) + suffix
            history.append(AssistantMessage(content=full_text, tool_calls=[]))
            await on_output(MessageEnd(text=full_text, tool_call_ids=[]))
            return full_text
        except LLMAPIError as exc:
            await on_output(ErrorOutput(message=_format_llm_error(exc), retryable=exc.retryable))
            full_text = "".join(text_chunks)
            if full_text:
                history.append(AssistantMessage(content=full_text, tool_calls=[]))
                await on_output(MessageEnd(text=full_text, tool_call_ids=[]))
            return full_text

        full_text = "".join(text_chunks)

        history.append(AssistantMessage(content=full_text, tool_calls=tool_calls))
        await on_output(MessageEnd(
            text=full_text, tool_call_ids=[tc.id for tc in tool_calls],
        ))

        # ------------------------------------------------------------------ #
        # Empty response (no text, no tool calls) → nudge and retry           #
        # ------------------------------------------------------------------ #
        if not full_text and not tool_calls:
            history.append(UserMessage(content=_EMPTY_RESPONSE_NUDGE))
            await on_output(NudgeOutput(text=_EMPTY_RESPONSE_NUDGE))
            continue

        # ------------------------------------------------------------------ #
        # No tool calls → we're done                                           #
        # ------------------------------------------------------------------ #
        if not tool_calls:
            return full_text

        # ------------------------------------------------------------------ #
        # Execute tool calls                                                   #
        # ------------------------------------------------------------------ #
        tool_results: list[ToolResultMessage] = []

        for i, tc in enumerate(tool_calls):
            call_output = ToolCallOutput(
                tool_call_id=tc.id,
                tool_name=tc.name,
                arguments=tc.arguments,
                needs_approval=tc.needs_approval,
            )
            await on_output(call_output)

            try:
                if tc.execute is None:
                    result = ToolResult(
                        content=f"Unknown tool '{tc.name}'.", is_error=True
                    )
                else:
                    # Validate args before approval — missing required args go straight back to LLM.
                    matched_tool = next((t for t in tools if t.name == tc.name), None)
                    validation_error = (
                        matched_tool.validate_arguments(tc.arguments) if matched_tool else None
                    )
                    if validation_error is not None:
                        result = validation_error
                    elif tc.needs_approval is False:
                        result = await tc.execute(**tc.arguments)
                    else:
                        # True  → on_permission_request checks whitelist first, then human
                        # "human" → on_permission_request skips whitelist, goes to human
                        approval = await on_permission_request(call_output)
                        if isinstance(approval, ToolResult):
                            # Denied with a reason — use the ToolResult directly
                            result = approval
                        elif not approval:
                            result = ToolResult(
                                content="Tool call was denied by the user.", is_error=True
                            )
                        else:
                            result = await tc.execute(**tc.arguments)
            except asyncio.CancelledError:
                for cancelled_tc in tool_calls[i:]:
                    cancelled_result = ToolResult(content=_INTERRUPTED, is_error=True)
                    await on_output(ToolResultOutput(
                        tool_call_id=cancelled_tc.id,
                        tool_name=cancelled_tc.name,
                        result=cancelled_result,
                    ))
                    tool_results.append(ToolResultMessage(
                        tool_call_id=cancelled_tc.id,
                        content=_INTERRUPTED,
                        is_error=True,
                    ))
                history.extend(tool_results)
                full_text = full_text + f"\n\n{_INTERRUPTED}"
                return full_text

            if context is not None and tc.truncation_allowed:
                result.content = truncate_tool_result(
                    result.content,
                    context.config.max_tool_output,
                    context.overflow_sink,
                )

            await on_output(ToolResultOutput(
                tool_call_id=tc.id,
                tool_name=tc.name,
                result=result,
                show_output=tc.show_output,
            ))
            tool_results.append(ToolResultMessage(
                tool_call_id=tc.id,
                content=result.content,
                is_error=result.is_error,
            ))

        history.extend(tool_results)

    raise RuntimeError(
        f"Agent loop exceeded maximum iterations ({_MAX_ITERATIONS}). "
        "This likely indicates an infinite tool-call cycle."
    )
