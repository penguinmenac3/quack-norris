"""OpenAI-compatible LLM providers using the official ``openai`` library.

Works with any OpenAI-compatible API including:
- OpenAI (https://api.openai.com/v1)
- Azure OpenAI (https://<resource>.openai.azure.com)
- Ollama (http://localhost:11434/v1)
- Any other OpenAI-compatible server

Supports streaming, thinking/reasoning tokens, and tool/function calling.
Matches the implementation in quack-norris-2.0 for consistency.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import openai

from quack_norris.core.llm.errors import LLMAPIError
from quack_norris.core.llm.provider import (
    AssistantMessage,
    ChatMessage,
    LLMOutput,
    TextDelta,
    ThinkingDelta,
    ToolDefinition,
    ToolResultMessage,
    UsageInfo,
)
from quack_norris.core.llm.tool import ToolCallRequest

_DEFAULT_BASE_URL = "http://localhost:11434/v1"


def _translate_openai_error(exc: openai.OpenAIError, model_name: str) -> LLMAPIError:
    """Translate an ``openai`` SDK exception into a normalised :class:`LLMAPIError`."""
    if isinstance(exc, openai.RateLimitError):
        return LLMAPIError(
            f"Rate limited while calling model '{model_name}': {exc}",
            status_code=429,
            retryable=True,
        )
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        return LLMAPIError(
            f"API error ({status}) while calling model '{model_name}': {exc}",
            status_code=status,
            retryable=status >= 500,
        )
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return LLMAPIError(
            f"Could not reach the API for model '{model_name}': {exc}",
            retryable=True,
        )
    return LLMAPIError(f"LLM request to '{model_name}' failed: {exc}")


def _encode_messages(
    system_prompt: str,
    chat_history: list[ChatMessage],
) -> list[dict[str, Any]]:
    encoded: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
        if isinstance(msg, ToolResultMessage):
            entry["tool_call_id"] = msg.tool_call_id
        encoded.append(entry)
    return encoded


def _encode_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    result = []
    for t in tools:
        props: dict[str, Any] = {}
        for name, param in t.parameters.items():
            p: dict[str, Any] = {"type": param.type, "description": param.description}
            if param.enum:
                p["enum"] = param.enum
            props[name] = p
        result.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": t.required,
                    },
                },
            }
        )
    return result


class OpenAIProvider:
    """Streams chat completions from any OpenAI-compatible API."""

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        api_key: str | None = None,
    ) -> None:
        self._client = openai.AsyncOpenAI(
            base_url=base_url.rstrip("/"),
            api_key=api_key or "unused",
        )

    async def list_models(self) -> list[str]:
        try:
            response = await self._client.models.list()
            return sorted({model.id for model in response.data}, key=str.casefold)
        except openai.OpenAIError as exc:
            raise _translate_openai_error(exc, "model discovery") from exc

    async def converse(
        self,
        model_name: str,
        system_prompt: str,
        tools: list[ToolDefinition],
        chat_history: list[ChatMessage],
    ) -> AsyncIterator[LLMOutput]:
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": _encode_messages(system_prompt, chat_history),
            "stream": True,
        }
        if tools:
            kwargs["tools"] = _encode_tools(tools)

        # Accumulators for streamed tool calls (index → {id, name, arguments_json})
        pending_calls: dict[int, dict[str, str]] = {}

        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # Content tokens
                if delta.content:
                    yield TextDelta(text=delta.content)

                # Thinking / reasoning tokens (custom field from some providers)
                reasoning = getattr(delta, "reasoning", None) or getattr(
                    delta, "reasoning_content", None
                )
                if reasoning:
                    yield ThinkingDelta(text=reasoning)

                # Tool call chunks — accumulate across streamed deltas
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in pending_calls:
                            pending_calls[idx] = {
                                "id": tc.id or "",
                                "name": (tc.function.name if tc.function else "") or "",
                                "arguments": "",
                            }
                        else:
                            if tc.id:
                                pending_calls[idx]["id"] = tc.id
                            if tc.function and tc.function.name:
                                pending_calls[idx]["name"] = tc.function.name
                        pending_calls[idx]["arguments"] += (
                            tc.function.arguments if tc.function else ""
                        ) or ""
        except openai.OpenAIError as exc:
            raise _translate_openai_error(exc, model_name) from exc

        # Emit accumulated tool calls as a single batch at the end
        if pending_calls:
            for _idx in sorted(pending_calls):
                entry = pending_calls[_idx]
                try:
                    args = json.loads(entry["arguments"]) if entry["arguments"] else {}
                except json.JSONDecodeError:
                    args = {"_raw": entry["arguments"]}
                yield ToolCallRequest(id=entry["id"], name=entry["name"], arguments=args)

        # Usage info — available on the final chunk via stream.get_final_completion()
        # but not directly yielded by the openai SDK chunks; emit zeros as placeholder.
        yield UsageInfo(input_tokens=0, output_tokens=0)


class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI provider using the official ``openai`` library."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_version: str,
    ) -> None:
        endpoint = base_url.rstrip("/")
        if endpoint.endswith("/openai"):
            endpoint = endpoint[: -len("/openai")]
        self._client = openai.AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
