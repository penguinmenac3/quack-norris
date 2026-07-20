"""AWS Bedrock Converse LLM provider via ``boto3``.

Ported from quack-norris-2.0.  Supports any Bedrock-compatible endpoint
including corporate proxies.  Authentication uses the
``AWS_BEARER_TOKEN_BEDROCK`` environment variable (set from the ``api_key``
config field).

boto3 is a blocking library, so streaming runs in a background thread and
results are forwarded to the async caller via an asyncio Queue.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import AsyncIterator
from typing import Any

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


class BedrockProvider:
    """Streams chat completions via AWS Bedrock Converse API."""

    def __init__(
        self,
        endpoint_url: str,
        api_key: str | None = None,
        region_name: str = "us-east-1",
    ) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for the AWSBedrock provider. "
                "Install it with:  uv pip install quack-norris-core[bedrock]  "
                "or:  uv pip install boto3"
            ) from exc

        self._endpoint_url = endpoint_url.rstrip("/")
        self._region_name = region_name
        if api_key:
            os.environ["AWS_BEARER_TOKEN_BEDROCK"] = api_key
        self._client = boto3.client(
            service_name="bedrock-runtime",
            endpoint_url=self._endpoint_url,
            region_name=self._region_name,
        )

    async def converse(
        self,
        model_name: str,
        system_prompt: str,
        tools: list[ToolDefinition],
        chat_history: list[ChatMessage],
    ) -> AsyncIterator[LLMOutput]:
        system_str, bedrock_messages = _encode_messages(system_prompt, chat_history)

        kwargs: dict[str, Any] = {
            "modelId": model_name,
            "messages": bedrock_messages,
        }
        if system_str:
            kwargs["system"] = [{"text": system_str}]
        if tools:
            kwargs["toolConfig"] = {"tools": _encode_tools(tools)}

        queue: asyncio.Queue[LLMOutput | None | Exception] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _produce() -> None:
            try:
                response = self._client.converse_stream(**kwargs)
                current_tool: dict[str, str] | None = None
                pending_tools: list[dict[str, str]] = []

                for event in response["stream"]:
                    if "contentBlockDelta" in event:
                        delta = event["contentBlockDelta"]["delta"]
                        if "text" in delta:
                            loop.call_soon_threadsafe(
                                queue.put_nowait, TextDelta(text=delta["text"])
                            )
                        if "reasoningContent" in delta:
                            thinking = delta["reasoningContent"].get("text", "")
                            if thinking:
                                loop.call_soon_threadsafe(
                                    queue.put_nowait, ThinkingDelta(text=thinking)
                                )
                        if "toolUse" in delta and current_tool is not None:
                            current_tool["arguments"] += delta["toolUse"].get("input", "")

                    elif "contentBlockStart" in event:
                        start = event["contentBlockStart"].get("start", {})
                        if "toolUse" in start:
                            current_tool = {
                                "id": start["toolUse"]["toolUseId"],
                                "name": start["toolUse"]["name"],
                                "arguments": "",
                            }

                    elif "contentBlockStop" in event:
                        if current_tool is not None:
                            pending_tools.append(current_tool)
                            current_tool = None

                    elif "metadata" in event:
                        usage = event["metadata"].get("usage", {})
                        if usage:
                            loop.call_soon_threadsafe(
                                queue.put_nowait,
                                UsageInfo(
                                    input_tokens=usage.get("inputTokens", 0),
                                    output_tokens=usage.get("outputTokens", 0),
                                ),
                            )

                # Emit all accumulated tool calls at the end
                for entry in pending_tools:
                    try:
                        args = json.loads(entry["arguments"]) if entry["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {"_raw": entry["arguments"]}
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        ToolCallRequest(id=entry["id"], name=entry["name"], arguments=args),
                    )

                loop.call_soon_threadsafe(queue.put_nowait, None)
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, exc)

        thread = threading.Thread(target=_produce, daemon=True)
        thread.start()

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item

        thread.join()


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------

def _encode_messages(
    system_prompt: str,
    chat_history: list[ChatMessage],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert to Bedrock Converse format.

    Returns ``(system_prompt_str, bedrock_messages)``.  Consecutive
    tool-result messages are merged into one ``user`` message to satisfy the
    Bedrock alternating-role constraint.
    """
    bedrock_msgs: list[dict[str, Any]] = []

    for msg in chat_history:
        if isinstance(msg, ToolResultMessage):
            tool_content: dict[str, Any] = {
                "toolResult": {
                    "toolUseId": msg.tool_call_id,
                    "content": [{"text": msg.content}],
                }
            }
            if bedrock_msgs and bedrock_msgs[-1]["role"] == "user":
                bedrock_msgs[-1]["content"].append(tool_content)
            else:
                bedrock_msgs.append({"role": "user", "content": [tool_content]})
            continue

        content: list[dict[str, Any]] = []
        if msg.content:
            content.append({"text": msg.content})

        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                content.append(
                    {
                        "toolUse": {
                            "toolUseId": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    }
                )

        if content:
            bedrock_msgs.append({"role": msg.role, "content": content})

    return system_prompt, bedrock_msgs


def _encode_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """Convert tool definitions to Bedrock Converse format."""
    result: list[dict[str, Any]] = []
    for t in tools:
        props: dict[str, Any] = {}
        for name, param in t.parameters.items():
            p: dict[str, Any] = {"type": param.type, "description": param.description}
            if param.enum:
                p["enum"] = param.enum
            props[name] = p
        spec: dict[str, Any] = {
            "name": t.name,
            "description": t.description,
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": props,
                    "required": t.required,
                }
            },
        }
        result.append({"toolSpec": spec})
    return result
