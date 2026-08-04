"""Terminal notification on "the CLI wants you back".

Emits a BEL (``\a``) — the terminal decides what that means (Windows Terminal:
taskbar flash / toast, and only when the window is unfocused; iTerm2, kitty,
GNOME Terminal behave the same). That is how we get focus-awareness without
polling window handles or adding a dependency.

Disable with ``QUACK_NO_BELL=1``.
"""

from __future__ import annotations

import os
import sys


def bell() -> None:
    """Ring the terminal bell if stderr is a TTY and bells aren't disabled."""
    if os.environ.get("QUACK_NO_BELL"):
        return
    if not sys.stderr.isatty():
        return
    sys.stderr.write("\a")
    sys.stderr.flush()
