import subprocess
import sys
import socket
from setproctitle import setproctitle

from quack_norris.common.config import read_config


def ui(config=None):
    from quack_norris.ui.app import main as _create_ui

    setproctitle("quack-norris-ui")
    if config is None:
        config = read_config("config.json", overwrites=sys.argv[1:])

    server_process = None
    if is_port_available(config["port"]):
        server_process = start_server_as_process(config)

    exit_code = _create_ui(config=config)
    if server_process is not None:
        server_process.kill()
    sys.exit(exit_code)


def is_port_available(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("localhost", port))
        return True
    except socket.error:
        return False
    finally:
        sock.close()


def start_server_as_process(config):
    """Starts the server as a subprocess."""
    print("Starting Server")
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    p = subprocess.Popen(
        [
            "quack-norris-server",
            f"--host={config['host']}",
            f"--port={config['port']}",
            f"--debug={config['debug']}",
        ],
        startupinfo=startupinfo,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
    )
    return p


def server():
    import uvicorn

    setproctitle("quack-norris-server")
    # Only load server config, if none is provided
    config = read_config("config.json", overwrites=sys.argv[1:])

    uvicorn.run(
        "quack_norris.server.api_server:app",
        host=config["host"],
        port=config["port"],
        reload=config["debug"],
    )


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
