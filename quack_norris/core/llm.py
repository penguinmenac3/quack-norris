from typing import Any, Callable, Generator, Optional, TypedDict
import concurrent.futures
import requests
import re
import json
import uuid

import openai
from openai import AzureOpenAI as _AzureAPI
from openai import OpenAI as _OpenAIAPI
from pydantic import BaseModel

from quack_norris.logging import logger
from quack_norris.core._prompts import TOOL_CALLING_PROMPT

MAX_TOKENS = 16384
#MAX_TOKENS = 4096


class ImageURL(BaseModel):
    url: str


class ChatContent(BaseModel):
    type: str
    text: Optional[str] = ""
    image_url: Optional[ImageURL] = None


class ToolParameter(TypedDict):
    type: str
    description: str

class Tool(BaseModel):
    name: str
    description: str
    parameters: dict[str, ToolParameter]
    tool_callable: Callable


class ToolCall(BaseModel):
    id: str
    tool: Tool
    params: dict[str, Any]


class ChatMessage(BaseModel):
    role: str
    content: str | list[ChatContent]
    tool_calls: Optional[list[str | ToolCall | Any]] = None
    tool_call_id: Optional[str] = None

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        else:
            for elem in self.content:
                if elem.type == "text" and elem.text is not None:
                    return elem.text
        return ""


class LLMStreamingResponse(object):
    def __init__(self, stream, tools: list[Tool]):
        self._stream = stream
        self._tools = tools
        self._tool_calls = None
        self._raw_text = None

    @property
    def stream(self) -> Generator[str, None, None]:
        is_tool_call = False
        is_thinking = False
        tool_calls: str = ""
        native_tool_calls = {}
        buffer: str = ""
        self._raw_text = ""
        for chunk in self._stream:
            if len(chunk.choices) == 0:
                continue
            token = chunk.choices[0].delta.content or ""
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
        self._tool_calls.extend(_parse_native_tool_calls(native_tool_calls, self._tools))

    @property
    def tool_calls(self) -> list[str | ToolCall]:
        if self._tool_calls is None:
            raise RuntimeError(
                "You must first stream the response, before you can retrieve the tool calls."
            )
        return self._tool_calls

    @property
    def text(self) -> str:
        if self._raw_text is None:
            raise RuntimeError(
                "You must first stream the response, before you can retrieve the text."
            )
        return self._raw_text.strip()


class ConnectionSpec(TypedDict):
    api_endpoint: str
    api_key: str
    provider: str  # "openai", "AzureOpenAI", "ollama"
    model: str  # model name or "AUTODETECT"
    config: dict  # any additional config for the model

class LLM(object):
    @staticmethod
    def from_config(config: dict[str, dict[str, ConnectionSpec]]) -> "LLM":
        if "llms" in config:
            connections = config["llms"]
        else:
            connections = {
                "Ollama": ConnectionSpec(
                    api_endpoint="http://localhost:11434",
                    api_key="ollama",
                    provider="ollama",
                    model="AUTODETECT",
                    config={}
                ),
            }

        return LLM(connections=connections)

    def __init__(self, connections: dict[str, ConnectionSpec]):
        self._llms = {}
        self._mapped_names = {}
        self._llms_configs = {}
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(self._add_connection, **conn, model_display_name=name)
                for name, conn in connections.items()
            ]
            for future in concurrent.futures.as_completed(futures):
                future.result()  # Raise exceptions if any
        logger.info(f"{len(self._llms.keys())} LLMs initialized")

    def _add_connection(self, api_endpoint: str, api_key: str, provider: str, model: str,
                        model_display_name: str, config: dict={}, api_version="2024-10-21"):
        logger.info(f"Connecting LLM: {model_display_name}")
        if provider == "ollama":
            if model == "AUTODETECT":
                modelListEndpoint = api_endpoint + "/api/tags"
                response = requests.get(modelListEndpoint)
                response.raise_for_status()
                data = response.json()
                models: list[str] = [model["name"] for model in data["models"]]
            else:
                models = [model]
            for model in models:
                self._llms[model] = _OpenAIAPI(base_url=api_endpoint + "/v1", api_key=api_key)
                self._llms_configs[model] = config
        else:
            if model == "AUTODETECT":
                raise ValueError("Model must be specified when not using ollama provider.")
            if provider == "AzureOpenAI":
                self._llms[model_display_name] = _AzureAPI(
                    api_version=api_version, base_url=api_endpoint, api_key=api_key
                )
                self._mapped_names[model_display_name] = model
                self._llms_configs[model_display_name] = config
            else:
                self._llms[model_display_name] = _OpenAIAPI(base_url=api_endpoint, api_key=api_key)
                self._mapped_names[model_display_name] = model
                self._llms_configs[model_display_name] = config

    def embeddings(self, model: str, input: str | list[str]) -> list[list[float]]:
        response = self._llms[model].embeddings.create(input=input, model=model)
        return [d.embedding for d in response.data]

    def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        remove_thoughts=True,
        tools: list[Tool] = [],
        system_prompt: str = "",
        no_think: bool = False,
        system_prompt_last: bool = False,
    ) -> tuple[str, list[str | ToolCall]]:
        actual_model = self._mapped_names[model] if model in self._mapped_names else model
        unofficial_toolcalling = self._llms_configs[model].get("unofficial_toolcalling", False)
        system_prompt_last = self._llms_configs[model].get("system_prompt_last", False)
        messages = self._prepare_messages(model, messages, tools, system_prompt, no_think, remove_thoughts, unofficial_toolcalling, system_prompt_last)
        try:
            if unofficial_toolcalling or len(tools) == 0:
                response = self._llms[model].chat.completions.create(
                    model=actual_model, messages=messages, stream=False
                )
            else:
                response = self._llms[model].chat.completions.create(
                    model=actual_model, messages=messages, stream=False, tools=self._prepare_tools(tools)
                )
        except openai.NotFoundError as e:
            raise RuntimeError(str(e))
        if isinstance(response, list):
            response = response[0]
        if response.choices[0].finish_reason == "error":
            raise RuntimeError(response.choices[0].message.content)
        response_str = response.choices[0].message.content or ""
        non_think_text = self._remove_thoughts_from_str(response_str)
        tool_calls = ""
        if len(tools) > 0 and "[CALL]" in non_think_text:
            tool_calls = "[CALL]".join(non_think_text.split("[CALL]")[1:])
            response_str = response_str.replace(tool_calls, "")
        return response_str.strip(), _parse_tool_calls(tool_calls.strip(), tools)

    def chat_stream(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[Tool] = [],
        system_prompt: str = "",
        no_think: bool = False,
        remove_thoughts=True,
    ) -> LLMStreamingResponse:
        actual_model = self._mapped_names[model] if model in self._mapped_names else model
        unofficial_toolcalling = self._llms_configs[model].get("unofficial_toolcalling", False)
        system_prompt_last = self._llms_configs[model].get("system_prompt_last", False)
        messages = self._prepare_messages(model, messages, tools, system_prompt, no_think, remove_thoughts, unofficial_toolcalling, system_prompt_last)
        try:
            if unofficial_toolcalling or len(tools) == 0:
                response = self._llms[model].chat.completions.create(
                    model=actual_model, messages=messages, stream=True
                )
            else:
                response = self._llms[model].chat.completions.create(
                    model=actual_model, messages=messages, stream=True, tools=self._prepare_tools(tools)
                )
        except openai.NotFoundError as e:
            raise RuntimeError(str(e))
        return LLMStreamingResponse(response, tools)
    
    def _prepare_tools(
        self,
        tools: list[Tool] = []
    ) -> list[dict[str, Any]]:
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

    def _prepare_messages(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[Tool],
        system_prompt: str,
        no_think: bool,
        remove_thoughts: bool,
        unofficial_toolcalling: bool,
        system_prompt_last: bool,
    ) -> list[ChatMessage]:
        if remove_thoughts:
            messages = [self._remove_thoughts(message) for message in messages]

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

        if len(tools) > 0 and unofficial_toolcalling:
            tool_prompt = LLM._build_tool_prompt(tools, TOOL_CALLING_PROMPT)
            system_prompt += "\n\n" + tool_prompt
        if no_think:
            system_prompt += " /no_think"  # Add /no_think to turn of thinking

        if system_prompt_last:
            messages = messages + [ChatMessage(role="system", content=system_prompt)]
        else:
            messages = [ChatMessage(role="system", content=system_prompt)] + messages

        return messages

    def _remove_thoughts_from_str(self, message: str) -> str:
        """Remove <think>...</think> tags from the string."""
        return re.sub(r"<think>.*?</think>", "", message, flags=re.DOTALL).strip()

    def _remove_thoughts(self, message: ChatMessage) -> ChatMessage:
        """Remove <think>...</think> tags from the message content."""
        message = message.model_copy()
        if isinstance(message.content, str):
            message.content = self._remove_thoughts_from_str(message.content)
        if isinstance(message.content, list):
            for content in message.content:
                if content.type == "text" and content.text is not None:
                    content.text = self._remove_thoughts_from_str(content.text)
        return message

    def get_models(self) -> list[str]:
        return list(self._llms.keys())

    @staticmethod
    def _build_tool_prompt(tools: list[Tool], tool_calling_prompt: str) -> str:
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


def _parse_native_tool_calls(tool_calls: dict[str, dict], tools: list[Tool]) -> list[str | ToolCall]:
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
