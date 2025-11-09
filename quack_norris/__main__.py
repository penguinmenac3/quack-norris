import asyncio
import argparse
import os
import json

from quack_norris.logging import logger, log_only_warn
from quack_norris.core.llm.types import LLM, ChatMessage
from quack_norris.core.llm.model_provider import ModelProvider
from quack_norris.core.output_writer import OutputWriter
from quack_norris.servers import serve_openai_api, ChatHandler
from quack_norris.servers.proxy_chat_handler import make_proxy_handlers
from quack_norris.agents import MultiAgentRunner
from quack_norris.tools.filesystem import FileSystemTools


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--serve",
        action="store_true",
        help="If you want to host a server instead of running directly via cli.",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="",
        help="If you want to have a single turn only, you can provide an input.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="If you want to log the output also into a file, set this to the path.",
    )
    parser.add_argument(
        "--workdir",
        type=str,
        default=os.curdir,
        help="A folder to which the llm has access.",
    )
    parser.add_argument(
        "--agent",
        type=str,
        default="agent.auto",
        help="Specify the agent that should be used. Note the prefix 'agent.*' is required. You can also use llms with 'proxy.*'.",
    )
    args = parser.parse_args()

    if not args.serve:
        log_only_warn()

    # Define paths
    config_path = os.path.join(
        os.path.expanduser("~"), ".config", "quack-norris", "config.json"
    )

    # Read the config
    logger.info("Loading config")
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = json.load(f)
    else:
        logger.error(f"No config found. Create a `{config_path}`.")
        exit(1)

    # Setup LLMs
    logger.info("Initializing LLMs")
    ModelProvider.load_config(config.get("llms", None))

    # Setup Chat
    handlers: dict[str, ChatHandler] = {}
    logger.info("Creating Proxies")
    handlers.update(make_proxy_handlers(config))
    logger.info("Creating Agents")
    multi_agent_runner = MultiAgentRunner.from_config(config, config_path)
    handlers.update(multi_agent_runner.make_chat_handlers())

    # Setup builtin tools
    fs_tools = FileSystemTools(root_folder=args.workdir, is_list_allowed=True, is_read_allowed=True, is_write_allowed=False, is_delete_allowed=False)
    multi_agent_runner.add_tools(fs_tools.list_tools(prefix="builtin."))

    if args.serve:
        logger.info("Starting server")
        serve_openai_api(handlers=handlers, port=11435)
    else:
        asyncio.run(cli_chat(handlers, args.agent, args.input, args.output))


async def cli_chat(handlers, agent: str, text: str, log_path: str):
    if agent not in handlers:
        agent_names = "\n  -".join([""] + list(handlers.keys()))
        logger.error(
            f"The selected agent is not a valid choice.\n  Select from:{agent_names}"
        )
        exit(22)  # Invalid argument
    chat_handler = handlers[agent]
    output = OutputWriter()
    history = []
    if text != "":
        if os.path.isfile(text):
            with open (text, "r", encoding="utf-8") as f:
                text = f.read()
        history.append(ChatMessage(role="user", content=text))
        await chat_handler(history=history, output=output)
        if log_path != "":
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(output.output_buffer)
    else:
        while True:
            text = ""
            while True:
                try:
                    line = input("> ")
                except EOFError:
                    exit(0)
                if line == "/exit":
                    exit(0)
                if line.endswith("\\"):
                    text += line[:-1] + "\n"
                else:
                    text += line
                    break
            history.append(ChatMessage(role="user", content=text))
            await chat_handler(history=list(history), output=output)
            history.append(ChatMessage(role="assistant", content=output.output_buffer))
            output.output_buffer = ""


if __name__ == "__main__":
    main()
