from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from acp import run_agent

from quack_norris.acp.server import QuackNorrisACPAgent
from quack_norris.core import LLM


def main() -> None:
    parser = argparse.ArgumentParser(prog="quack-norris")
    parser.add_argument("command", nargs="?", choices=["acp"], default="acp")
    parser.add_argument("--config", metavar="FILE")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr)
    LLM.setup(args.config)
    asyncio.run(run_agent(QuackNorrisACPAgent()))


if __name__ == "__main__":
    main()
