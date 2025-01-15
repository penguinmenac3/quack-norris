from quack_norris.server._types import EmbedResponse, TextResponse, Message
from quack_norris.server.user import User


class Router(object):
    def __init__(self):
        pass

    def embeddings(self, model: str, inputs: list[str], data: dict[str, any], user: User) -> EmbedResponse:
        return EmbedResponse(prompt_tokens=0, total_tokens=0, embeds=[])

    def complete(self, model: str, prompt: str, data: dict[str, any], user: User) -> TextResponse:
        return TextResponse(prompt_tokens=0, total_tokens=0, finish_reason="stop", result="")

    def chat(self, model: str, messages: list[Message], data: dict[str, any], user: User) -> TextResponse:
        return TextResponse(prompt_tokens=0, total_tokens=0, finish_reason="stop", result="")


router = Router()
