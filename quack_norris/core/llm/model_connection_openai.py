import requests
import os
import openai
from openai import AzureOpenAI as _AzureAPI
from openai import OpenAI as _OpenAIAPI
from openai._types import NOT_GIVEN

from quack_norris.core.llm.types import Tool, ChatMessage, LLMResponse
from quack_norris.core.llm.model_provider import ModelConnector, register_model_connector
from quack_norris.core.llm.utils import tools_to_openai, tools_to_custom_prompt, messages_to_openai
from quack_norris.core.llm.response_custom import CustomToolCallingResponse, CustomToolCallingResponseStream
from quack_norris.core.llm.response_openai import OpenAIToolCallingResponse, OpenAIToolCallingResponseStream


@register_model_connector("OpenAI", "AzureOpenAI", "ollama")
class OpenAIModelConnection(ModelConnector):
    def __init__(self,  api_endpoint: str, api_key: str, provider: str, model: str,
                        config: dict={}, api_version="2024-10-21"):
        self._config = config
        self._models: dict[str, str] = {}
        prompt_path = config.get(
            "custom_tool_call_prompt",
            os.path.join(os.path.dirname(__file__), "custom_tool_call_prompt.md"),
        )
        with open(prompt_path, "r") as f:
            self.custom_tool_calling_prompt = f.read()

        if provider == "ollama":
            if model == "AUTODETECT":
                modelListEndpoint = api_endpoint + "/api/tags"
                response = requests.get(modelListEndpoint)
                response.raise_for_status()
                data = response.json()
                self._models = {
                    config.get("name_prefix", "") + model["name"]: model["name"]
                    for model in data["models"]
                }
            else:
                self._models = {config.get("name", model): model}
            self._client = _OpenAIAPI(base_url=api_endpoint + "/v1", api_key=api_key)
        elif provider == "AzureOpenAI" or provider == "OpenAI":
            if model == "AUTODETECT":
                raise ValueError("Model must be specified when not using ollama provider.")
            if provider == "AzureOpenAI":
                self._client = _AzureAPI(
                    api_version=api_version, base_url=api_endpoint, api_key=api_key
                )
                self._models = {config.get("name", model): model}
            else:
                self._client = _OpenAIAPI(base_url=api_endpoint, api_key=api_key)
                self._models = {config.get("name", model): model}

    def embeddings(self, model: str, input: str | list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(input=input, model=self._models[model])
        return [d.embedding for d in response.data]

    def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[Tool] = [],
        system_prompt: str = "",
        remove_thoughts: bool = True,
        stream: bool = True,
    ) -> LLMResponse:
        unofficial_toolcalling = self._config.get("unofficial_toolcalling", False)

        messages = messages_to_openai(messages, remove_thoughts)
        if len(tools) > 0 and unofficial_toolcalling:
            tool_prompt = tools_to_custom_prompt(tools, self.custom_tool_calling_prompt)
            system_prompt += "\n\n" + tool_prompt
        
        # Disable thinking for models that support /no_think
        if self._config.get("no_think", False):
            system_prompt += " /no_think"

        # depending on model putting the system prompt last improve performance
        if self._config.get("system_prompt_last", False):
            messages = messages + [ChatMessage(role="system", content=system_prompt)]
        else:
            messages = [ChatMessage(role="system", content=system_prompt)] + messages

        # disable streaming (response can fake stream)
        if self._config.get("never_stream", False):
            stream = False

        # only pass text of messages (in case endpoint does not support images)
        if self._config.get("text_only", False):
            messages = [
                ChatMessage(role=msg.role, content=msg.text()) for msg in messages
            ]

        try:
            if unofficial_toolcalling or len(tools) == 0:
                openai_tools = NOT_GIVEN
            else:
                openai_tools = tools_to_openai(tools)
            response = self._client.chat.completions.create(
                messages=messages,  # type: ignore
                model=self._models[model],
                stream=stream,
                max_tokens=self._config.get("max_tokens", NOT_GIVEN),
                tools=openai_tools  # type: ignore
            )
        except openai.NotFoundError as e:
            raise RuntimeError(str(e))
        if stream:    
            if unofficial_toolcalling:
                return CustomToolCallingResponseStream(response, tools)
            else:
                return OpenAIToolCallingResponseStream(response, tools)
        else:
            if unofficial_toolcalling:
                return CustomToolCallingResponse(response, tools)
            else:
                return OpenAIToolCallingResponse(response, tools)

    def get_models(self) -> list[str]:
        return list(self._models.keys())
