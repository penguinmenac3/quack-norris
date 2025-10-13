from typing import Any
import traceback

from quack_norris.core import (
    LLM,
    ChatMessage,
    OutputWriter,
)
from quack_norris.servers.openai_server import ChatHandler


def make_proxy_handlers(config: dict[str, Any], llm: LLM) -> dict[str, ChatHandler]:
    if "proxy" not in config:
        print("WARNING: No proxy configuration found in config, no models will be proxied.")
        return {}

    # Serve agents via chat api
    def _make_handler(model_name: str):
        async def _handle_chat(history: list[ChatMessage], output: OutputWriter) -> None:
            # Try with streaming
            try:
                response = llm.chat_stream(model=model_name, messages=history)
                for token in response.stream:
                    await output.write(token, clean=False)
                return
            except:
                print("WARNING: Failed to use streaming api, trying non streaming.")
            # Try without streaming
            try:
                text, _ = llm.chat(model=model_name, messages=history)
                await output.write(text, clean=False)
                return
            except:
                print("WARNING: Failed to use non-streaming api, trying with just text.")
            # Last ditch effort, just get text
            try:
                history = [
                    ChatMessage(role=msg.role, content=msg.text()) for msg in history
                ]
                text, _ = llm.chat(model=model_name, messages=history)
                await output.write(text, clean=False)
                return
            except:
                print("ERROR: Completely failed to retrieve.")
                traceback.print_exc()
                await output.write("ERROR: The selected LLM has an error. Please try again later and contact the admin if the error persists.", clean=False)

        return _handle_chat
    return {k: _make_handler(k) for k in llm.get_models() if k in config["proxy"]}
