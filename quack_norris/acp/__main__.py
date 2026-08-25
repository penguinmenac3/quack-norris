from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from acp import run_agent

from quack_norris.acp.server import QuackNorrisACPAgent
from quack_norris.core import LLM
from quack_norris.core.llm.providers.copilot import get_copilot_token


def main() -> None:
    parser = argparse.ArgumentParser(prog="quack-norris")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ACP command
    acp_parser = subparsers.add_parser("acp", help="Run ACP agent")
    acp_parser.add_argument("--config", metavar="FILE")

    # Login command
    login_parser = subparsers.add_parser("login-copilot", help="Authenticate with GitHub Copilot")
    login_parser.add_argument("--enterprise-domain", help="GitHub Enterprise domain (e.g., your-company.ghe.com)")

    args = parser.parse_args()

    if args.command == "login-copilot":
        try:
            get_copilot_token(args.enterprise_domain)
            print("✓ Successfully authenticated with GitHub Copilot")
        except Exception as e:
            print(f"✗ Authentication failed: {e}")
            sys.exit(1)
    else:  # Default to ACP
        logging.basicConfig(stream=sys.stderr)
        LLM.setup(args.config)
        asyncio.run(run_agent(QuackNorrisACPAgent()))


if __name__ == "__main__":
    main()
