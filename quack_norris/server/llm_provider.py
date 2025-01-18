import os
from openai import OpenAI as _OpenAIAPI
from quack_norris.server._types import TextResponse, EmbedResponse, Message


class LlmProvider(object):
    def chat(self, model: str, messages: list[Message]) -> TextResponse:
        raise NotImplementedError("Must be implemented by subclass!")

    def complete(self, model: str, prompt: str) -> TextResponse:
        raise NotImplementedError("Must be implemented by subclass!")

    def embed(self, model: str, inputs: list[str]) -> EmbedResponse:
        raise NotImplementedError("Must be implemented by subclass!")


class OpenAIProvider(LlmProvider):
    def __init__(self, base_url, api_key):
        self._client = _OpenAIAPI(base_url=base_url, api_key=api_key)

    def chat(self, model: str, messages: list[Message]) -> TextResponse:
        response = self._client.chat.completions.create(
            model=model,
            messages=[message._asdict() for message in messages]
        )
        return TextResponse(
            prompt_tokens=response.usage.prompt_tokens,
            total_tokens=response.usage.total_tokens,
            finish_reason=response.choices[0].finish_reason,
            result=response.choices[0].message.content,
        )

    def complete(self, model: str, prompt: str) -> TextResponse:
        response = self._client.completions.create(
            model=model,
            prompt=prompt
        )
        return TextResponse(
            prompt_tokens=response.usage.prompt_tokens,
            total_tokens=response.usage.total_tokens,
            finish_reason=response.choices[0].finish_reason,
            result=response.choices[0].text,
        )

    def embed(self, model: str, inputs: list[str]) -> EmbedResponse:
        response = self._client.embeddings.create(
            model=model,
            input=inputs
        )
        return EmbedResponse(
            prompt_tokens=response.usage.prompt_tokens,
            total_tokens=response.usage.total_tokens,
            embeds=response.data[0].embedding
        )


class OllamaProvider(OpenAIProvider):
    def __init__(self, base_url='http://localhost:11434'):
        super().__init__(base_url=os.path.join(base_url, "v1").replace("\\", "/"), api_key='ollama')
