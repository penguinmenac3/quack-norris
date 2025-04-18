from typing import Generator, NamedTuple, Callable

from quack_norris.common._types import ChatCompletionRequest, EmbeddingRequest
from quack_norris.common.config import read_config
from quack_norris.common.llm_provider import LLM, LLMMultiplexer


class Command(NamedTuple):
    command: str
    args: list[str]


class QuackNorris(LLM):

    def __init__(self):
        config = read_config("config.json")
        self._default_model = config["default_model"]
        self._role = "default"
        self._llm = LLMMultiplexer()

    def get_models(self) -> list[str]:
        return ["quack-norris"] + [f"quack-norris/{model}" for model in self._llm.get_models()]

    def embeddings(self, request: EmbeddingRequest) -> list[list[float]]:
        if request.model == "quack-norris":
            request.model = "nomic-embed-text"
        if request.model.startswith("quack-norris/"):
            request.model = request.model.replace("quack-norris/", "")
        return self._llm.embeddings(request)

    def chat(self, request: ChatCompletionRequest) -> str | Generator[str, None, None]:
        if request.model == "quack-norris":
            request.model = self._default_model
        if request.model.startswith("quack-norris/"):
            request.model = request.model.replace("quack-norris/", "")
        msg = request.messages[-1].content
        command = self._detect_command(msg)
        if command is not None:
            request.model = "command"
            return command()
        else:
            # Remove commands and command outputs from chat history
            messages = []
            last_command = False
            for msg in request.messages:
                if self._detect_command(msg.content) is not None:
                    last_command = True
                    continue
                if not last_command:
                    messages.append(msg)
                last_command = False
            request.messages = messages
            return self._llm.chat(request)

    def _detect_command(self, msg: str) -> Callable[[], str] | None:
        words = msg.strip().replace("\n", " ").split(" ")
        HELP = "Available Commands:\n"

        HELP += _help_entry("/persona", "Get the currently selected persona.")
        if len(words) >= 1 and "/persona" == words[-1]:
            return lambda: "Selecting personas not implemented yet"

        HELP += _help_entry("/persona list", "Get a list of available personas.")
        HELP += _help_entry("/persona <name>", "Set the persona")
        if len(words) >= 2 and "/persona" == words[-2]:
            persona = words[-1]
            if persona == "list":
                return lambda: "Listing personas not implemented yet"
            else:
                return lambda: "Changing personas not implemented yet"

        HELP += _help_entry("/help", "Get all available commands.")
        if len(words) >= 1 and "/help" == words[-1]:
            return lambda: HELP
        return None


def _help_entry(command: str, description: str) -> str:
    return f"* `{command}`: {description}\n"
