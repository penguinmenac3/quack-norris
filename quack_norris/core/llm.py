from typing import Any, Callable, Generator, Optional, TypedDict
import requests
import os
import re
import json

import openai
from openai import AzureOpenAI as _AzureAPI
from openai import OpenAI as _OpenAIAPI
from pydantic import BaseModel

from quack_norris.core.prompts import TOOL_CALLING_PROMPT


class ImageURL(BaseModel):
    url: str


class ChatContent(BaseModel):
    type: str
    text: Optional[str] = ""
    image_url: Optional[ImageURL] = None


class ChatMessage(BaseModel):
    role: str
    content: str | list[ChatContent]

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        else:
            for elem in self.content:
                if elem.type == "text" and elem.text is not None:
                    return elem.text
        return ""


class Tool(BaseModel):
    name: str
    description: str
    arguments: str
    tool_callable: Callable


class ToolCall(BaseModel):
    tool: Tool
    params: dict[str, Any]


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
        buffer: str = ""
        self._raw_text = ""
        for chunk in self._stream:
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


class LLM(object):
    @staticmethod
    def from_config(work_dir: str | None = None, fname: str = "llms.json") -> "LLM":
        if work_dir is None:
            home = os.path.expanduser("~")
            work_dir = os.path.join(home, ".config/quack-norris")
        llms_path = os.path.join(work_dir, fname)
        if not os.path.exists(llms_path):
            connections = {
                "Ollama": ConnectionSpec(
                    api_endpoint="http://localhost:11434",
                    api_key="ollama",
                    provider="ollama",
                    model="AUTODETECT",
                ),
            }
        else:
            with open(llms_path, "r") as f:
                connections = json.load(f)

        return LLM(connections=connections)

    def __init__(self, connections: dict[str, ConnectionSpec]):
        self._llms = {}
        self._mapped_names = {}
        for name, conn in connections.items():
            self._add_connection(**conn, model_display_name=name)

    def _add_connection(self, api_endpoint: str, api_key: str, provider: str, model: str, model_display_name: str):
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
        else:
            if model == "AUTODETECT":
                raise ValueError("Model must be specified when not using ollama provider.")
            if provider == "AzureOpenAI":
                self._llms[model_display_name] = _AzureAPI(
                    api_version="2024-10-21", base_url=api_endpoint, api_key=api_key
                )
                self._mapped_names[model_display_name] = model
            else:
                self._llms[model_display_name] = _OpenAIAPI(base_url=api_endpoint, api_key=api_key)
                self._mapped_names[model_display_name] = model

    def embeddings(self, model: str, input: str | list[str]) -> list[list[float]]:
        response = self._llms[model].embeddings.create(input=input, model=model)
        return [d.embedding for d in response.data]

    def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        max_tokens: int = 16384,
        remove_thoughts=True,
        tools: list[Tool] = [],
        tool_calling_prompt: str = TOOL_CALLING_PROMPT,
        system_prompt: str = "",
        no_think: bool = False,
        system_prompt_last: bool = False,
    ) -> tuple[str, list[str | ToolCall]]:
        try:
            if remove_thoughts:
                messages = [self._remove_thoughts(message) for message in messages]
            if system_prompt != "":
                system_prompt = LLM.build_system_prompt(
                    system_prompt, tools, tool_calling_prompt, no_think
                )
                if system_prompt_last:
                    messages = messages + [ChatMessage(role="system", content=system_prompt)]
                else:
                    messages = [ChatMessage(role="system", content=system_prompt)] + messages
            
            actual_model = self._mapped_names[model] if model in self._mapped_names else model
            response = self._llms[model].chat.completions.create(
                model=actual_model, messages=messages, max_tokens=max_tokens, stream=False
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
        max_tokens: int = -1,
        remove_thoughts=True,
        tools: list[Tool] = [],
        tool_calling_prompt: str = TOOL_CALLING_PROMPT,
        system_prompt: str = "",
        no_think: bool = False,
        system_prompt_last: bool = False,
    ) -> LLMStreamingResponse:
        try:
            if remove_thoughts:
                messages = [self._remove_thoughts(message) for message in messages]
            if system_prompt != "":
                system_prompt = LLM.build_system_prompt(
                    system_prompt, tools, tool_calling_prompt, no_think
                )
                if system_prompt_last:
                    messages = messages + [ChatMessage(role="system", content=system_prompt)]
                else:
                    messages = [ChatMessage(role="system", content=system_prompt)] + messages
                    
            actual_model = self._mapped_names[model] if model in self._mapped_names else model
            response = self._llms[model].chat.completions.create(
                model=actual_model, messages=messages, max_tokens=max_tokens, stream=True
            )
        except openai.NotFoundError as e:
            raise RuntimeError(str(e))
        return LLMStreamingResponse(response, tools)

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
    def build_system_prompt(
        system_prompt: str,
        tools: list[Tool],
        tool_calling_prompt: str,
        no_think: bool,
    ) -> str:
        if len(tools) > 0:
            tool_prompt = LLM._build_tool_prompt(tools, tool_calling_prompt)
            system_prompt += "\n\n" + tool_prompt
        if no_think:
            pass
            # system_prompt += " /no_think"  # Add /no_think to turn of thinking
        return system_prompt

    @staticmethod
    def _build_tool_prompt(tools: list[Tool], tool_calling_prompt: str) -> str:
        tool_descriptions: list[str] = []
        for tool in tools:
            description = tool.description
            if description.endswith("."):
                description = description[:-1]
            tool_descriptions.append(
                f"* {tool.name.lower()}: {description}.\n{tool.arguments}".strip()
            )
        return tool_calling_prompt.format(tools="\n".join(tool_descriptions))


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
            out.append(f"Failed to load tool call `{tool_call}` with the following error: `{e}`.")
            continue
        found = False
        for tool in tools:
            if tool.name.lower() == tool_name:
                out.append(ToolCall(tool=tool, params=args))
                found = True
                break
        if not found:
            out.append(f"Tool '{tool_name}' not found.")
    return out
