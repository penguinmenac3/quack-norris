import asyncio
import argparse
import os
import json

from quack_norris.logging import logger, log_only_warn
from quack_norris.core import LLM, ChatMessage, OutputWriter
from quack_norris.servers import serve_openai_api, ChatHandler
from quack_norris.servers.proxy_chat_handler import make_proxy_handlers
from quack_norris.agents import MultiAgentRunner


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
    llm = LLM.from_config(config)

    # Setup Chat
    handlers: dict[str, ChatHandler] = {}
    logger.info("Creating Proxies")
    handlers.update(make_proxy_handlers(config, llm))
    logger.info("Creating Agents")
    multi_agent_runner = MultiAgentRunner.from_config(config, llm, config_path)
    handlers.update(multi_agent_runner.make_chat_handlers())

    if args.serve:
        logger.info("Starting server")
        serve_openai_api(handlers=handlers, port=11435)
    else:
        asyncio.run(cli_chat(handlers, args.agent, args.input))


async def cli_chat(handlers, agent: str, text: str):
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
        history.append(ChatMessage(role="user", content=text))
        await chat_handler(history=history, output=output)
    else:
        while True:
            text = ""
            while True:
                line = input("> ")
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
