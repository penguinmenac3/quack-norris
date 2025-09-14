from typing import Generator, List, Optional
import requests
import os
import re

import openai
from openai import AzureOpenAI as _AzureAPI
from openai import OpenAI as _OpenAIAPI
from pydantic import BaseModel


class ImageURL(BaseModel):
    url: str


class ChatContent(BaseModel):
    type: str
    text: Optional[str] = ""
    image_url: Optional[ImageURL] = None


class ChatMessage(BaseModel):
    role: str
    content: str | List[ChatContent]

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        else:
            for elem in self.content:
                if elem.type == "text" and elem.text is not None:
                    return elem.text
        return ""


class LLM(object):
    @staticmethod
    def from_env() -> tuple["LLM", str]:
        llm = LLM(
            api_endpoint=os.environ.get("API_ENDPOINT", "http://localhost:11434"),
            api_key=os.environ.get("API_KEY", "ollama"),
            provider=os.environ.get("PROVIDER", "ollama"),
            model=os.environ.get("MODEL", "AUTODETECT"),
        )
        model = os.environ.get("MODEL", "qwen3:4b")
        return llm, model

    def __init__(
        self, api_endpoint: str, api_key: str, provider: str = "OpenAI", model: str = "AUTODETECT"
    ):
        self._llms = {}
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
                self._llms[model] = _AzureAPI(
                    api_version="2024-10-21", base_url=api_endpoint, api_key=api_key
                )
            else:
                self._llms[model] = _OpenAIAPI(base_url=api_endpoint, api_key=api_key)

    def embeddings(self, model: str, input: str | List[str]) -> List[List[float]]:
        response = self._llms[model].embeddings.create(input=input, model=model)
        return [d.embedding for d in response.data]

    def chat(
        self, model: str, messages: List[ChatMessage], max_tokens: int = -1, remove_thoughts=True
    ) -> str:
        try:
            if remove_thoughts:
                messages = [self._remove_thoughts(message) for message in messages]
            response = self._llms[model].chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, stream=False
            )
        except openai.NotFoundError as e:
            raise RuntimeError(str(e))
        if response.choices[0].finish_reason == "error":
            raise RuntimeError(response.choices[0].message.content)
        return response.choices[0].message.content or ""

    def chat_stream(
        self, model: str, messages: List[ChatMessage], max_tokens: int = -1, remove_thoughts=True
    ) -> Generator[str, None, None]:
        try:
            if remove_thoughts:
                messages = [self._remove_thoughts(message) for message in messages]
            response = self._llms[model].chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, stream=True
            )
        except openai.NotFoundError as e:
            raise RuntimeError(str(e))
        return LLM._stream_wrapper(response)

    def _remove_thoughts(self, message: ChatMessage) -> ChatMessage:
        """Remove <think>...</think> tags from the message content."""
        message = message.model_copy()
        if isinstance(message.content, str):
            message.content = re.sub(
                r"<think>.*?</think>", "", message.content, flags=re.DOTALL
            ).strip()
        if isinstance(message.content, list):
            for content in message.content:
                if content.type == "text" and content.text is not None:
                    content.text = re.sub(
                        r"<think>.*?</think>", "", content.text, flags=re.DOTALL
                    ).strip()
        return message

    def get_models(self) -> list[str]:
        return list(self._llms.keys())

    @staticmethod
    def _stream_wrapper(stream):
        for chunk in stream:
            yield chunk.choices[0].delta.content or ""
