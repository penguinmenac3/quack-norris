import sys
from argparse import ArgumentParser

from quack_norris.server.api_server import main as _api_server
from quack_norris.config import read_config


def ui():
    parser = ArgumentParser("quack-norris-ui")
    _ = parser.parse_args()
    raise NotImplementedError()


def server():
    parser = ArgumentParser("quack-norris-server")
    config = read_config("server.json")
    parser.add_argument("--host", required=False, default=config["host"], help="A host to overwrite the config temporarily.")
    parser.add_argument("--port", required=False, default=config["port"], help="A port to overwrite the config temporarily.")
    args = parser.parse_args()
    _api_server(host=args.host, port=args.port)


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
