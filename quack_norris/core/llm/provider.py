"""LLM protocol contract — provider interface plus all input/output types."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from quack_norris.core.llm.tool import ToolCallRequest


# ---------------------------------------------------------------------------
# Stream output types (what LLMProvider.converse yields)
# ---------------------------------------------------------------------------

@dataclass
class TextDelta:
    """A streamed chunk of assistant text."""

    text: str


@dataclass
class ThinkingDelta:
    """A streamed chunk of model reasoning (CoT models)."""

    text: str


@dataclass
class UsageInfo:
    """Token usage for a completed turn."""

    input_tokens: int
    output_tokens: int


# A single item the LLM stream can yield
LLMOutput = TextDelta | ThinkingDelta | ToolCallRequest | UsageInfo


# ---------------------------------------------------------------------------
# Chat history message types (what LLMProvider.converse receives)
# ---------------------------------------------------------------------------

@dataclass
class SystemMessage:
    role: Literal["system"] = field(default="system", init=False)
    content: str


@dataclass
class UserMessage:
    role: Literal["user"] = field(default="user", init=False)
    content: str


@dataclass
class CheckpointMessage(UserMessage):
    """A summary standing in for a dropped prefix of the conversation.

    Wire-wise this *is* a user message — providers dispatch on ``role`` and see
    ``"user"`` — but it stays a distinct type in memory so history
    reconstruction can tell a checkpoint apart from something the human typed.

    ``replaced_count`` is the number of messages it stands in for, counted
    against the *raw* message list replayed from storage (not the current
    in-memory list).  Checkpoints therefore subsume each other: a later
    checkpoint always has a larger count and its summary already folds in the
    earlier one.
    """

    replaced_count: int = 0


@dataclass
class AssistantMessage:
    role: Literal["assistant"] = field(default="assistant", init=False)
    content: str
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


@dataclass
class ToolResultMessage:
    role: Literal["tool"] = field(default="tool", init=False)
    tool_call_id: str
    content: str
    is_error: bool = False


ChatMessage = UserMessage | AssistantMessage | ToolResultMessage


# ---------------------------------------------------------------------------
# Internal wire types — ToolDefinition / ToolParameter
# (used only inside the provider implementations to format API requests)
# ---------------------------------------------------------------------------

@dataclass
class ToolParameter:
    type: str
    description: str
    enum: list[str] | None = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, ToolParameter]
    required: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LLMProvider protocol
# ---------------------------------------------------------------------------

class LLMProvider(Protocol):
    """
    A provider wraps one base URL + API key and knows which models it serves.

    It must NOT be tied to a specific model — model selection happens at call
    time via ``model_name``.
    """

    async def converse(
        self,
        model_name: str,
        system_prompt: str,
        tools: list[ToolDefinition],
        chat_history: list[ChatMessage],
    ) -> AsyncIterator[LLMOutput]:
        """
        Stream a conversation turn.

        Yields :class:`LLMOutput` items:
        - :class:`TextDelta` — streamed text chunks
        - :class:`ThinkingDelta` — CoT reasoning chunks
        - :class:`~quack_norris.core.llm.tool.ToolCallRequest` — tool call requests
        - :class:`UsageInfo` — final token usage
        """
        ...
