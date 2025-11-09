from typing import Any, Callable, Generator, Optional, TypedDict, Protocol
from pydantic import BaseModel


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


class LLMResponse(object):
    def __init__(self, raw_text: Optional[str] = None, tool_calls: Optional[list[str | ToolCall]] = None):
        """
        You can either provide raw_text and tool_calls, if you already have them.

        If you are having a streamed response, then overwrite the stream property
        and fill out `self._tool_calls` and `self._raw_text` while streaming.
        """
        self._tool_calls = tool_calls
        self._raw_text = raw_text

    @property
    def stream(self) -> Generator[str, None, None]:
        if self._raw_text is None:
            raise NotImplementedError("Must be implemented by a subclass for native or custom toolcalls")
        
        for token in self._raw_text.split(" "):
            yield token + " "
        
        if self._tool_calls is None:
            self._tool_calls = []

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


class LLM(Protocol):
    def __call__(
        self,
        messages: list[ChatMessage],
        tools: list[Tool] = [],
        system_prompt: str = "",
        remove_thoughts: bool = True,
        stream: bool = True,
        no_think: bool = False,
    ) -> LLMResponse:
        raise NotImplementedError()


class Embedder(Protocol):
    def __call__(self, model: str, input: str | list[str]) -> list[list[float]]:
        raise NotImplementedError()


class ModelConnectionSpec(TypedDict):
    api_endpoint: str
    api_key: str
    provider: str  # "openai", "AzureOpenAI", "ollama"
    model: str  # model name or "AUTODETECT"
    config: dict  # any additional config for the model
