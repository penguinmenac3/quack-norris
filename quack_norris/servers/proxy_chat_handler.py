from typing import Any
import traceback

from quack_norris.logging import logger
from quack_norris.core.llm.types import LLM, ChatMessage
from quack_norris.core.llm.model_provider import ModelProvider
from quack_norris.core.output_writer import OutputWriter
from quack_norris.servers.openai_server import ChatHandler


def make_proxy_handlers(config: dict[str, Any]) -> dict[str, ChatHandler]:
    if "proxy" not in config:
        logger.warning(
            "No proxy configuration found in config, no models will be proxied."
        )
        return {}

    # Serve agents via chat api
    def _make_handler(model_name: str):
        async def _handle_chat(history: list[ChatMessage], output: OutputWriter) -> None:
            try:
                llm = ModelProvider.get_llm(model_name)
                response = llm(messages=history, stream=True)
                for token in response.stream:
                    await output.write(token, clean=False)
                return
            except:
                logger.warning(
                    "WARNING: Failed to use streaming api, trying non streaming."
                )
                traceback.print_exc()
                await output.write("ERROR: The selected LLM has an error. Please try again later and contact the admin if the error persists.", clean=False)

        return _handle_chat
    return {f"proxy.{k}": _make_handler(k) for k in ModelProvider.get_models() if k in config["proxy"]}
