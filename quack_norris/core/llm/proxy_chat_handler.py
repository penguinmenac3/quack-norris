import traceback

from quack_norris.logging import logger
from quack_norris.api.chat_handler import ChatHandler, ChatHandlerProvider, ChatHandlerRegistry
from quack_norris.core.llm.types import ChatMessage
from quack_norris.core.llm.model_provider import ModelProvider
from quack_norris.core.output_writer import OutputWriter
from quack_norris.config import Config


class ProxyChatHandlerProvider(ChatHandlerProvider):
    def __init__(self, proxies: list[str]) -> None:
        self._proxies = proxies

    @staticmethod
    def setup_from_config(config: Config) -> None:
        if "proxy" not in config:
            logger.warning(
                "No proxy configuration found in config, no models will be proxied."
            )
            return
        proxies: list[str] = [f"proxy.{k}" for k in ModelProvider.get_models() if k in config["proxy"]]
        handler = ProxyChatHandlerProvider(proxies)
        ChatHandlerRegistry.register_handler_provider(handler)

    def get_handler(self, name: str) -> ChatHandler:
        if name not in self._proxies:
            raise RuntimeError(f"Model/Agent '{name}' not found in proxy provider.")
        model_name = name.replace("proxy.", "")
        async def _chat_handler(
            history: list[ChatMessage], workspace: str, output: OutputWriter
        ) -> None:
            try:
                llm = ModelProvider.get_llm(model_name)
                response = llm(messages=history, stream=True)
                for token in response.stream:
                    await output.write(token, separate=False, clean=False)
                return
            except:
                logger.warning(
                    "WARNING: Failed to use streaming api, trying non streaming."
                )
                traceback.print_exc()
                await output.write(
                    "ERROR: The selected LLM has an error. Please try again later and contact the admin if the error persists.",
                    separate=False,
                    clean=False,
                )
        return _chat_handler


    def list_handlers(self) -> list[str]:
        return self._proxies
