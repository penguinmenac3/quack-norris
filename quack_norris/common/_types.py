from typing import List, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    max_tokens: Optional[int] = 512
    temperature: Optional[float] = 0.1
    stream: Optional[bool] = False


class OllamaChatCompletionRequest(ChatCompletionRequest):
    stream: Optional[bool] = True


class EmbeddingRequest(BaseModel):
    model: str
    input: str | List[str]
