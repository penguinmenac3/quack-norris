from quack_norris.api.chat_handler import ChatHandlerRegistry
import argparse
import os

from quack_norris.api.server import serve_openai_api
from quack_norris.api.cli import cli_chat
from quack_norris.core.llm.model_provider import ModelProvider
from quack_norris.core.llm.proxy_chat_handler import ProxyChatHandlerProvider
from quack_norris.config import Config
from quack_norris.logging import logger, log_only_warn
from quack_norris.ui.app import create_ui
from quack_norris.core.agents.agent_provider import AgentProvider
from quack_norris.core.agents.loader import load_and_watch_agents_and_skills


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Name of the config to use (must be in cwd, ~/.config/quack_norris/, or PATH_TO_CODE/quack_norris/configs).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="If you want to enable debug mode.",
    )
    parser.add_argument(
        "--workdir",
        type=str,
        default=os.curdir,
        help="A folder to which the llm has access.",
    )
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
        "--agent",
        type=str,
        default="agent.auto",
        help="Specify the agent that should be used. Note the prefix 'agent.*' is required. You can also use llms with 'proxy.*'.",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default="",
        help="The workspace name for the agent to use, defaults to '' (no workspace).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.input != "":
        log_only_warn()  # Reduce logging for single input mode

    if args.workdir != os.curdir:
        logger.info(f"Changing working directory to `{args.workdir}`")
        os.chdir(args.workdir)

    config = Config(args.config, overwrites={"debug": args.debug})
    if args.debug:
        logger.debug(f"Using config {config}")
    if not args.serve and args.input == "":
        create_ui(config)
        return

    ModelProvider.initialize(config)
    load_and_watch_agents_and_skills(config)
    handler_registry = ChatHandlerRegistry()
    handler_registry.register_handler_provider(ProxyChatHandlerProvider(config))
    handler_registry.register_handler_provider(AgentProvider())
    if args.serve:
        serve_openai_api(handler_registry, config=config, port=11435)
    elif args.input != "":
        cli_chat(handler_registry, args.agent, args.input, args.workspace, args.output)


if __name__ == "__main__":
    main()
