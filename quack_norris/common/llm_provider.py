import os

import tiktoken
from openai import OpenAI as _OpenAIAPI
from openai.types import CompletionUsage

from quack_norris.common._types import EmbedResponse, Message, TextResponse


class LlmProvider(object):

    def get_token_count(
        self,
        model: str,
        prompt_or_messages: str | list[Message],
        usage: CompletionUsage | None,
        result: str,
    ):
        if usage is None:
            if "gpt" in model.lower():
                encoding = tiktoken.get_encoding("gpt2")
            else:
                encoding = tiktoken.get_encoding("cl100k")
            if isinstance(prompt_or_messages, str):
                prompt_tokens = len(encoding.encode(prompt_or_messages))
                total_tokens = prompt_tokens + len(encoding.encode(result))
            else:
                # For chat messages, compute the number of tokens
                prompt_tokens = 0
                for message in prompt_or_messages:
                    prompt_tokens += 3  # Tokens per message
                    prompt_tokens += len(encoding.encode(message.role))
                    prompt_tokens += len(encoding.encode(message.content))
                prompt_tokens += 3
                total_tokens = prompt_tokens + len(encoding.encode(result))
        else:
            prompt_tokens = usage.prompt_tokens
            total_tokens = usage.total_tokens
        return prompt_tokens, total_tokens

    def chat(self, model: str, messages: list[Message]) -> TextResponse:
        raise NotImplementedError("Must be implemented by subclass!")

    def complete(self, model: str, prompt: str) -> TextResponse:
        raise NotImplementedError("Must be implemented by subclass!")

    def embeddings(self, model: str, inputs: list[str]) -> EmbedResponse:
        raise NotImplementedError("Must be implemented by subclass!")


class OpenAIProvider(LlmProvider):
    def __init__(self, base_url, api_key):
        self._client = _OpenAIAPI(base_url=base_url, api_key=api_key)

    def chat(self, model: str, messages: list[Message]) -> TextResponse:
        response = self._client.chat.completions.create(
            model=model,
            messages=[message._asdict() for message in messages],  # type: ignore
        )
        result = response.choices[0].message.content or ""
        prompt_tokens, total_tokens = self.get_token_count(model, messages, response.usage, result)
        return TextResponse(
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            finish_reason=response.choices[0].finish_reason,
            result=result,
        )

    def complete(self, model: str, prompt: str) -> TextResponse:
        response = self._client.completions.create(
            model=model,
            prompt=prompt
        )
        result = response.choices[0].text or ""
        prompt_tokens, total_tokens = self.get_token_count(model, prompt, response.usage, result)
        return TextResponse(
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            finish_reason=response.choices[0].finish_reason,
            result=result,
        )

    def embeddings(self, model: str, inputs: list[str]) -> EmbedResponse:
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
