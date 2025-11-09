from typing import Generator
import json
import uuid

from quack_norris.core.llm.types import Tool, LLMResponse, ToolCall
from quack_norris.core.llm.utils import remove_thoughts_from_str


class CustomToolCallingResponse(LLMResponse):
    def __init__(self, response, tools: list[Tool]):
        if isinstance(response, list):
            response = response[0]
        if response.choices[0].finish_reason == "error":
            raise RuntimeError(response.choices[0].message.content)
        text = response.choices[0].message.content or ""
        non_think_text = remove_thoughts_from_str(text)
        tool_calls = ""
        if len(tools) > 0 and "[CALL]" in non_think_text:
            tool_calls = "[CALL]".join(non_think_text.split("[CALL]")[1:])
            text = text.replace(tool_calls, "")
        super().__init__(text, _parse_tool_calls(tool_calls, tools))


class CustomToolCallingResponseStream(LLMResponse):
    def __init__(self, stream, tools: list[Tool]):
        super().__init__()
        self._stream = stream
        self._tools = tools

    @property
    def stream(self) -> Generator[str, None, None]:
        is_tool_call = False
        is_thinking = False
        tool_calls: str = ""
        buffer: str = ""
        self._raw_text = ""
        for chunk in self._stream:
            if len(chunk.choices) == 0:
                continue
            token = chunk.choices[0].delta.content or ""
            self._raw_text += token  # Collect full text
            token_buffer: str = ""
            for char in token:
                if is_tool_call:
                    tool_calls += char
                elif char == "<":
                    if buffer != "":
                        yield buffer
                    buffer = char
                elif char == "[" and not is_thinking:
                    if buffer != "":
                        yield buffer
                    buffer = char
                elif buffer != "":
                    if char in [">", "]", " ", "\n", "\t"]:
                        word: str = buffer + char
                        buffer = ""
                        if word == "<think>":
                            is_thinking = True
                        if word == "</think>":
                            is_thinking = False
                        if not is_thinking and word == "[CALL]" and len(self._tools) > 0:
                            is_tool_call = True
                            word = ""
                        if word != "":
                            yield word
                    else:
                        buffer += char
                else:
                    token_buffer += char
            if token_buffer != "":
                yield token_buffer
        if buffer != "":
            yield buffer

        self._tool_calls = _parse_tool_calls(tool_calls.strip(), self._tools)


def _parse_tool_calls(tool_calls: str, tools: list[Tool]) -> list[str | ToolCall]:
    out = []
    for tool_call in tool_calls.split("[CALL]"):
        if tool_call.strip() == "":
            continue
        try:
            spec = json.loads(tool_call)
            tool_name = spec["name"].lower()
            args = spec["parameters"]
        except Exception as e:
            out.append(f"Failed to load tool call with the following error: `{e}`.\n\n"
                       "Detected Toolcall:\n```\n{tool_call}\n```\n\n"
                       "Possible reasons are:\n"
                       "  - `Extra data`: You wrote somehting else after the tool call. The tool call has to be your last output.\n"
                       "  - `Keyerror`: Your json object did not adhere to the format requiring `parameters` and `name` on top level.\n"
                       "Make sure your message ends on a tool call with no text after it and that it adheres to the correct format.")
            continue
        found = False
        for tool in tools:
            if tool.name.lower() == tool_name:
                out.append(ToolCall(id=str(uuid.uuid4()), tool=tool, params=args))
                found = True
                break
        if not found:
            out.append(f"Tool '{tool_name}' not found.")
    return out
