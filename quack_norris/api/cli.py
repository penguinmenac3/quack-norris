import os
import asyncio

from quack_norris.logging import logger
from quack_norris.core.llm.types import ChatMessage
from quack_norris.core.output_writer import OutputWriter
from quack_norris.api.chat_handler import ChatHandlerRegistry


def cli_chat(agent: str, text: str, log_path: str):
    try:
        chat_handler = ChatHandlerRegistry.get_handler(agent)
    except RuntimeError as e:
        agent_names = "\n  -".join([""] + ChatHandlerRegistry.list_handlers())
        logger.error(
            f"The selected agent is not a valid choice.\n  Select from:{agent_names}"
        )
        exit(22)  # Invalid argument
    output = OutputWriter()
    history = []
    if os.path.isfile(text):
        with open(text, "r", encoding="utf-8") as f:
            text = f.read()
    history.append(ChatMessage(role="user", content=text))
    asyncio.run(chat_handler(history=history, workspace="", output=output))
    if log_path != "":
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(output.output_buffer)
