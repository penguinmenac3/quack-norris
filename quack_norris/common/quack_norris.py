from typing import Generator, List

from quack_norris.common._types import ChatCompletionRequest, EmbeddingRequest
from quack_norris.common.config import read_config
from quack_norris.common.llm_provider import LLM, LLMMultiplexer


class QuackNorris(LLM):

    def __init__(self):
        config = read_config("config.json")
        self._default_model = config["default_model"]
        self._llm = LLMMultiplexer()

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
            msg = request.messages[-1].content.strip()
            words = msg.replace("\n", " ").split(" ")
            # Hanlde model check command
            if len(words) >= 1 and "/model" == words[-1]:
                return f"Current model is '{self._default_model}'."
            # Hanlde model switch command
            if len(words) >= 2 and "/model" == words[-2]:
                model = words[-1]
                models = self._llm.get_models()
                if model in models:
                    self._default_model = model
                    return f"Switched model to '{model}'."
                else:
                    model_list = "\n* ".join([""] + models)
                    return f"Model '{model}' not available.\n\nAvailable models:{model_list}"
            return self._llm.chat(request)

    def get_models(self) -> list[str]:
        return ["quack-norris"] + self._llm.get_models()
