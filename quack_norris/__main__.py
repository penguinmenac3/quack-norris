import sys
from setproctitle import setproctitle

from quack_norris.common.config import read_config


def ui(config=None):
    from quack_norris.ui.app import main as _create_ui

    setproctitle("quack-norris-ui")
    if config is None:
        config = read_config("config.json", overwrites=sys.argv[1:])

    exit_code = _create_ui(config=config)
    sys.exit(exit_code)


if __name__ == "__main__":
    ui()
