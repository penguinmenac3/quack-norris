from typing import Any
import json
import re
import uuid

from quack_norris.core.llm.types import ChatMessage, Tool, ToolCall


def remove_thoughts_from_str(message: str) -> str:
    """Remove <think>...</think> tags from the string."""
    return re.sub(r"<think>.*?</think>", "", message, flags=re.DOTALL).strip()


def remove_thoughts(message: ChatMessage) -> ChatMessage:
    """Remove <think>...</think> tags from the message content."""
    message = message.model_copy()
    if isinstance(message.content, str):
        message.content = remove_thoughts_from_str(message.content)
    if isinstance(message.content, list):
        for content in message.content:
            if content.type == "text" and content.text is not None:
                content.text = remove_thoughts_from_str(content.text)
    return message


def tools_to_openai(tools: list[Tool] = []) -> list[dict[str, Any]]:
    """Convert from our tool type to the tool format that openai needs."""
    result = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": tool.parameters,
                    "required": list(tool.parameters.keys()),
                },
            }
        }
        for tool in tools
    ]
    return result


def tools_to_custom_prompt(tools: list[Tool], tool_calling_prompt: str) -> str:
    """
    Convert from our tool type to a custom tool calling promt.
    
    This can be used to allow LLMs without official tool calling support to call tools.
    """
    tool_descriptions: list[str] = []
    for tool in tools:
        description = tool.description
        if description.endswith("."):
            description = description[:-1]
        parameters = ""
        for param_name, param_details in tool.parameters.items():
            parameters += f"  - {param_name}: {param_details['description']}\n"
        tool_descriptions.append(
            f"* {tool.name.lower()}: {description}.\n{parameters}\n".strip()
        )
    return tool_calling_prompt.format(tools="\n".join(tool_descriptions))


def messages_to_openai(messages: list[ChatMessage], is_remove_thoughts: bool) -> list[ChatMessage]:
    """
    Convert the messages to adhere to the openai format.

    Specifically replace tool calls with the OpenAI format in the history.
    """
    if is_remove_thoughts:
        messages = [remove_thoughts(message) for message in messages]

    # Convert tool calls to openai format
    for message in messages:
        if message.tool_calls is not None:
            message.tool_calls = [
                {
                    "id": tc.id if hasattr(tc, "id") else str(uuid.uuid4()),
                    "type": "function",
                    "function": {
                        "name": tc.tool.name if hasattr(tc, "tool") else "",
                        "arguments": json.dumps(tc.params) if hasattr(tc, "params") else "{}"
                    }
                }
                for tc in message.tool_calls
                if isinstance(tc, ToolCall)
            ]
    return messages
