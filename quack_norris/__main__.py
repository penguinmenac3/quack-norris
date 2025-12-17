import argparse
import os

from quack_norris.api.server import serve_openai_api
from quack_norris.api.cli import cli_chat
from quack_norris.core.llm.model_provider import ModelProvider
from quack_norris.core.llm.proxy_chat_handler import ProxyChatHandlerProvider
from quack_norris.core.agents.multi_agent_runner import MultiAgentRunner
from quack_norris.config import Config
from quack_norris.logging import logger, log_only_warn
from quack_norris.ui.app import create_ui


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
    return parser.parse_args()


def main():
    args = parse_args()
    if args.input != "":
        log_only_warn()  # Reduce logging for single input mode

    if args.workdir != os.curdir:
        logger.info(f"Changing working directory to `{args.workdir}`")
        os.chdir(args.workdir)

    config = Config(args.config, overwrites={"debug": args.debug})
    logger.warning(f"Using config {config}")
    if args.serve:
        ModelProvider.initialize(config)
        ProxyChatHandlerProvider.setup_from_config(config)
        MultiAgentRunner.setup_from_config(config)
        serve_openai_api(config=config, port=11435)
    elif args.input != "":
        ModelProvider.initialize(config)
        ProxyChatHandlerProvider.setup_from_config(config)
        MultiAgentRunner.setup_from_config(config)
        cli_chat(args.agent, args.input, args.output)
    else:
        create_ui(config)


if __name__ == "__main__":
    main()
