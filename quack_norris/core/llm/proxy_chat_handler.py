from typing import AsyncGenerator
import traceback

from quack_norris.logging import logger
from quack_norris.api.chat_handler import ChatHandler, ChatHandlerProvider
from quack_norris.core.llm.types import ChatMessage
from quack_norris.core.llm.model_provider import ModelProvider
from quack_norris.config import Config


class ProxyChatHandlerProvider(ChatHandlerProvider):
    def __init__(self, config: Config) -> None:
        if "proxy" not in config:
            logger.warning("No proxy configuration found in config, no models will be proxied.")
            return
        proxies: list[str] = [
            f"proxy.{k}" for k in ModelProvider.get_models() if k in config["proxy"]
        ]
        self._proxies = proxies

    def get_handler(self, name: str) -> ChatHandler:
        if name not in self._proxies:
            raise RuntimeError(f"Model/Agent '{name}' not found in proxy provider.")
        model_name = name.replace("proxy.", "")

        async def _chat_handler(
            history: list[ChatMessage], workspace: str, **kwargs
        ) -> AsyncGenerator[str, None]:
            try:
                llm = ModelProvider.get_llm(model_name)
                response = llm(messages=history, stream=True)
                for token in response.stream:
                    yield token
                return
            except:
                logger.warning(
                    "WARNING: Failed to use streaming api, trying non streaming."
                )
                traceback.print_exc()
                yield "ERROR: The selected LLM has an error. Please try again later and contact the admin if the error persists.\n"
        return _chat_handler


    def list_handlers(self) -> list[str]:
        return self._proxies
