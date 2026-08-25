from __future__ import annotations

from pathlib import Path

from quack_norris.core.llm import Tool
from quack_norris.tools.background import ProcessRegistry
from quack_norris.tools.background_tools import make_operation_tools
from quack_norris.tools.files import make_file_tools
from quack_norris.tools.shell import make_shell_tool


def make_native_tools(
    workspace: str | Path,
    *,
    skills: bool,
) -> list[Tool]:
    root = Path(workspace).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Workspace must be an existing directory: {workspace}")

    def get_cwd() -> Path:
        return root

    registry = ProcessRegistry()
    tools = [
        *make_file_tools(get_cwd),
        make_shell_tool(get_cwd, registry),
        *make_operation_tools(registry),
    ]

    if skills:
        from quack_norris.skills_and_agents import make_skill_invoke_tool

        tools.append(make_skill_invoke_tool(root))

    return tools
