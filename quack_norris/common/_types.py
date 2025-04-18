from typing import List, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    max_tokens: Optional[int] = -1
    temperature: Optional[float] = -1
    stream: Optional[bool] = False


class OllamaChatCompletionRequest(ChatCompletionRequest):
    stream: Optional[bool] = True


class OllamaModelInfoRequest(BaseModel):
    name: str


class EmbeddingRequest(BaseModel):
    model: str
    input: str | List[str]
