from typing import Protocol
from quack_norris.core.llm.types import ChatMessage
from quack_norris.core.output_writer import OutputWriter


class ChatHandler(Protocol):
    async def __call__(
        self, history: list[ChatMessage], workspace: str, output: OutputWriter
    ) -> None: ...


class ChatHandlerProvider(Protocol):
    def get_handler(self, name: str) -> ChatHandler: ...
    def list_handlers(self) -> list[str]: ...


def register_handler(name: str):
    def decorator(handler: ChatHandler) -> ChatHandler:
        ChatHandlerRegistry.register_handler(name, handler)
        return handler
    return decorator


def register_handler_provider(provider: ChatHandlerProvider):
    ChatHandlerRegistry.register_handler_provider(provider)
    return provider


class ChatHandlerRegistry():
    _handlers: dict[str, ChatHandler] = {}
    _handler_providers = []

    @staticmethod
    def register_handler(name: str, handler: ChatHandler) -> None:
        ChatHandlerRegistry._handlers[name] = handler

    @staticmethod
    def register_handler_provider(provider: ChatHandlerProvider) -> None:
        if provider not in ChatHandlerRegistry._handler_providers:
            ChatHandlerRegistry._handler_providers.append(provider)

    @staticmethod
    def get_handler(name: str) -> ChatHandler:
        # Try resolving in reverse order of registration, so that newest are prefered
        for provider in reversed(ChatHandlerRegistry._handler_providers):
            try:
                return provider.get_handler(name)
            except RuntimeError:
                continue
        try:
            return ChatHandlerRegistry._handlers[name]
        except KeyError:
            raise RuntimeError(f"Model/Agent '{name}' not found. Available models/agents: {', '.join(ChatHandlerRegistry.list_handlers())}")

    @staticmethod
    def list_handlers() -> list[str]:
        all_handlers = set(ChatHandlerRegistry._handlers.keys())
        for provider in ChatHandlerRegistry._handler_providers:
            all_handlers.update(provider.list_handlers())
        return list(all_handlers)
