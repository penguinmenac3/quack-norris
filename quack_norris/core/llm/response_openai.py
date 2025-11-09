from typing import Generator
import json

from quack_norris.core.llm.types import Tool, LLMResponse, ToolCall


class OpenAIToolCallingResponse(LLMResponse):
    def __init__(self, response, tools: list[Tool]):
        if isinstance(response, list):
            response = response[0]
        if response.choices[0].finish_reason == "error":
            raise RuntimeError(response.choices[0].message.content)
        text = response.choices[0].message.content or ""
        tool_calls = {}
        if hasattr(response.choices[0].message, "tool_calls") and response.choices[0].message.tool_calls is not None:
            for idx, tool_call in enumerate(response.choices[0].message.tool_calls):
                tool_calls[idx] = {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                    "id": tool_call.id
                }

        super().__init__(text, _parse_openai_tool_calls(tool_calls, tools))


class OpenAIToolCallingResponseStream(LLMResponse):
    def __init__(self, stream, tools: list[Tool]):
        super().__init__()
        self._stream = stream
        self._tools = tools

    @property
    def stream(self) -> Generator[str, None, None]:
        native_tool_calls = {}
        self._raw_text = ""
        for chunk in self._stream:
            if len(chunk.choices) == 0:
                continue
            for tool_call in chunk.choices[0].delta.tool_calls or []:
                if tool_call.index not in native_tool_calls:
                    native_tool_calls[tool_call.index] = {
                        "id": "",
                        "name": "",
                        "arguments": ""
                    }
                if tool_call.id is not None:
                    native_tool_calls[tool_call.index]["id"] = tool_call.id
                if tool_call.function.name is not None:
                    native_tool_calls[tool_call.index]["name"] = tool_call.function.name
                if tool_call.function.arguments is not None:
                    native_tool_calls[tool_call.index]["arguments"] += tool_call.function.arguments
            token = chunk.choices[0].delta.content or ""
            if token != "":
                self._raw_text += token
                yield token

        self._tool_calls = _parse_openai_tool_calls(native_tool_calls, self._tools)


def _parse_openai_tool_calls(tool_calls: dict[str, dict], tools: list[Tool]) -> list[str | ToolCall]:
    out = []
    for tool_call in tool_calls.values():
        tool_name = tool_call["name"]
        args = tool_call["arguments"]
        call_id = tool_call["id"]
        if isinstance(args, str):
            if args != "":
                args = json.loads(args)
            else:
                args = {}
        found = False
        for tool in tools:
            if tool.name.lower() == tool_name:
                out.append(ToolCall(id=call_id, tool=tool, params=args))
                found = True
                break
        if not found:
            out.append(f"Tool '{tool_name}' not found.")
    return out
