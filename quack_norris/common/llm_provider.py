from typing import Generator, List
import openai
from openai import OpenAI as _OpenAIAPI

from quack_norris.common._types import ChatCompletionRequest, EmbeddingRequest


class LLM(object):

    def embeddings(self, request: EmbeddingRequest) -> List[List[float]]:
        raise NotImplementedError("Must be implemented by subclass!")

    def chat(self, request: ChatCompletionRequest) -> str | Generator[str, None, None]:
        raise NotImplementedError("Must be implemented by subclass!")


class OpenAI(LLM):
    def __init__(self, base_url="http://localhost:11434/v1", api_key="ollama"):
        self._client = _OpenAIAPI(base_url=base_url, api_key=api_key)

    def embeddings(self, request: EmbeddingRequest) -> List[List[float]]:
        response = self._client.embeddings.create(**request.model_dump())
        return [d.embedding for d in response.data]

    def chat(self, request: ChatCompletionRequest) -> str | Generator[str, None, None]:
        try:
            response = self._client.chat.completions.create(**request.model_dump())
        except openai.NotFoundError as e:
            raise RuntimeError(str(e))
        if request.stream:
            return OpenAI._stream_wrapper(response)
        else:
            if response.choices[0].finish_reason == "error":
                raise RuntimeError(response.choices[0].message.content)
            return response.choices[0].message.content or ""

    @staticmethod
    def _stream_wrapper(stream):
        for chunk in stream:
            yield chunk.choices[0].delta.content or ""


class QuackNorris(LLM):
    def __init__(self, llm: LLM | None = None, default_model: str = "gemma3:12b"):
        self._llm = llm or OpenAI()
        self._default_model = default_model

    def embeddings(self, request: EmbeddingRequest) -> List[List[float]]:
        if request.model != "quack-norris":
            return self._llm.embeddings(request)
        else:
            request.model = "nomic-embed-text"
            return self._llm.embeddings(request)

    def chat(self, request: ChatCompletionRequest) -> str | Generator[str, None, None]:
        if request.model != "quack-norris":
            return self._llm.chat(request)
        else:
            request.model = self._default_model
            return self._llm.chat(request)
