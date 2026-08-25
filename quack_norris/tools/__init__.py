"""Built-in tools for the QuackNorris agent."""

from quack_norris.tools.background import ProcessRegistry
from quack_norris.tools.background_tools import make_background_tools, make_operation_tools
from quack_norris.tools.files import make_file_tools
from quack_norris.tools.shell import make_shell_tool

__all__ = [
    "ProcessRegistry",
    "make_background_tools",
    "make_file_tools",
    "make_operation_tools",
    "make_shell_tool",
]
