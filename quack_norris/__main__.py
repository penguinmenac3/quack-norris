import sys
from argparse import ArgumentParser

from setproctitle import setproctitle

from quack_norris.common.config import read_config


def ui():
    from quack_norris.ui.app import main as _create_ui
    setproctitle("quack-norris-ui")
    parser = ArgumentParser("quack-norris-ui")
    config = read_config("ui.json")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()
    config["debug"] = args.debug
    _create_ui(config=config)


def server():
    import uvicorn

    setproctitle("quack-norris-server")
    parser = ArgumentParser("quack-norris-server")
    config = read_config("server.json")
    parser.add_argument(
        "--host",
        required=False,
        default=config["host"],
        type=str,
        help="A host to overwrite the config temporarily.",
    )
    parser.add_argument(
        "--port",
        required=False,
        default=config["port"],
        type=int,
        help="A port to overwrite the config temporarily.",
    )
    parser.add_argument("--debug", action="store_true", help="Run the flask server in debug mode.")
    args = parser.parse_args()
    uvicorn.run("quack_norris.server.api_server:app", host=args.host, port=args.port, reload=True)


def main():
    route = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    if route == "server":
        server()
    elif route == "ui":
        ui()
    else:
        print("usage: quack-norris [-h] mode")
        print()
        print("positional arguments:")
        print("  mode      'ui' or 'server' specifies what you want to run.")
        exit(1)


if __name__ == "__main__":
    main()
