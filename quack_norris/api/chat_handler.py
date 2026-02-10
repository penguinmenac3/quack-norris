from typing import Protocol, AsyncGenerator
from quack_norris.core.llm.types import ChatMessage


class ChatHandler(Protocol):
    def __call__(
        self, history: list[ChatMessage], workspace: str, **kwargs
    ) -> AsyncGenerator[str, None]: ...


class ChatHandlerProvider(Protocol):
    def get_handler(self, name: str) -> ChatHandler: ...
    def list_handlers(self) -> list[str]: ...


class ChatHandlerRegistry():
    def __init__(self):
        self._handlers: dict[str, ChatHandler] = {}
        self._handler_providers = []

    def register_handler(self, name: str, handler: ChatHandler) -> None:
        self._handlers[name] = handler

    def register_handler_provider(self, provider: ChatHandlerProvider) -> None:
        if provider not in self._handler_providers:
            self._handler_providers.append(provider)

    def get_handler(self, name: str) -> ChatHandler:
        # Try resolving in reverse order of registration, so that newest are prefered
        for provider in reversed(self._handler_providers):
            try:
                return provider.get_handler(name)
            except RuntimeError:
                continue
        try:
            return self._handlers[name]
        except KeyError:
            raise RuntimeError(
                f"Model/Agent '{name}' not found. Available models/agents: {', '.join(self.list_handlers())}"
            )

    def list_handlers(self) -> list[str]:
        all_handlers = set(self._handlers.keys())
        for provider in self._handler_providers:
            all_handlers.update(provider.list_handlers())
        return list(all_handlers)
