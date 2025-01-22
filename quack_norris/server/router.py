from typing import Any

from quack_norris.common._types import EmbedResponse, Message, TextResponse
from quack_norris.common.llm_provider import OllamaProvider
from quack_norris.server.user import User


class Router(object):
    def __init__(self):
        self.llm_provider = OllamaProvider()

    def embeddings(
        self, model: str, inputs: list[str], data: dict[str, Any], user: User
    ) -> EmbedResponse:
        if model.startswith("quack-norris"):
            return EmbedResponse(prompt_tokens=0, total_tokens=0, embeds=[])
        else:
            return self.llm_provider.embeddings(model, inputs)

    def complete(self, model: str, prompt: str, data: dict[str, Any], user: User) -> TextResponse:
        if model.startswith("quack-norris"):
            return TextResponse(
                prompt_tokens=0, total_tokens=0, finish_reason="stop", result="complete"
            )
        else:
            return self.llm_provider.complete(model, prompt)

    def chat(
        self, model: str, messages: list[Message], data: dict[str, Any], user: User
    ) -> TextResponse:
        if model.startswith("quack-norris"):
            return TextResponse(
                prompt_tokens=0, total_tokens=0, finish_reason="stop", result="CHAT NOT IMPLEMENTED"
            )
        else:
            return self.llm_provider.chat(model, messages)


router = Router()
