from typing import Generator, List
import requests
import openai
from openai import OpenAI as _OpenAIAPI

from quack_norris.common._types import ChatCompletionRequest, EmbeddingRequest
from quack_norris.common.config import read_config


class LLM(object):

    def embeddings(self, request: EmbeddingRequest) -> List[List[float]]:
        raise NotImplementedError("Must be implemented by subclass!")

    def chat(self, request: ChatCompletionRequest) -> str | Generator[str, None, None]:
        raise NotImplementedError("Must be implemented by subclass!")


class OpenAI(LLM):

    def __init__(self, base_url, api_key):
        self._client = _OpenAIAPI(base_url=base_url, api_key=api_key)

    def embeddings(self, request: EmbeddingRequest) -> List[List[float]]:
        response = self._client.embeddings.create(**request.model_dump())
        return [d.embedding for d in response.data]

    def chat(self, request: ChatCompletionRequest) -> str | Generator[str, None, None]:
        try:
            params = request.model_dump()
            if "max_tokens" in params and params["max_tokens"] == -1:
                del params["max_tokens"]
            if "temperature" in params and params["temperature"] == -1:
                del params["temperature"]
            response = self._client.chat.completions.create(**params)
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


class LLMMultiplexer(LLM):
    def __init__(self):
        config = read_config("config.json")
        self._llms = {}
        self._llm_models = {}
        for key, details in config["llms"].items():
            if key == "ollama" and details["model"] == "AUTODETECT":
                # FIXME detect all available models
                modelListEndpoint = details["apiEndpoint"] + "/api/tags"
                response = requests.get(modelListEndpoint)
                response.raise_for_status()
                data = response.json()
                for model in data["models"]:
                    name = model["name"]
                    self._llm_models[name] = name
                    apiEndpoint = details["apiEndpoint"] + "/v1"
                    self._llms[name] = OpenAI(base_url=apiEndpoint, api_key=details["apiKey"])
            else:
                self._llm_models[key] = details["model"]
                self._llms[key] = OpenAI(base_url=details["apiEndpoint"], api_key=details["apiKey"])

    def embeddings(self, request: EmbeddingRequest) -> List[List[float]]:
        model_id = request.model
        request.model = self._llm_models[model_id]
        return self._llms[model_id].embeddings(request)

    def chat(self, request: ChatCompletionRequest) -> str | Generator[str, None, None]:
        model_id = request.model
        request.model = self._llm_models[model_id]
        return self._llms[model_id].chat(request)

    def get_models(self) -> list[str]:
        return list(self._llms.keys())
