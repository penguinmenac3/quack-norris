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
