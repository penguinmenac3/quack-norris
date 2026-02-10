import os
import asyncio

from quack_norris.logging import logger
from quack_norris.core.llm.types import ChatMessage
from quack_norris.api.chat_handler import ChatHandlerRegistry


def cli_chat(
    handler_registry: ChatHandlerRegistry, agent: str, text: str, workspace: str, log_path: str
):
    # Get the chat handler for the specified agent
    try:
        chat_handler = handler_registry.get_handler(agent)
    except RuntimeError:
        agent_names = "\n  -".join([""] + handler_registry.list_handlers())
        logger.error(f"The selected agent is not a valid choice.\n  Select from:{agent_names}")
        exit(22)  # Invalid argument

    # If the text is a file path, read the content
    if os.path.isfile(text):
        with open(text, "r", encoding="utf-8") as f:
            text = f.read()

    # Run the chat handler in an async context
    async def run_chat_handler() -> str:
        generator = await chat_handler(
            history=[ChatMessage(role="user", content=text)], workspace=workspace
        )
        response = ""
        async for chunk in generator:
            response += chunk
            print(chunk, end="", flush=True)
        return response

    response = asyncio.run(run_chat_handler())

    # Log the response if a log path is provided
    if log_path != "":
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(response)
