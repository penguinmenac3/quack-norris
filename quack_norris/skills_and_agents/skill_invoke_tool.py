from __future__ import annotations

from pathlib import Path
from typing import Annotated

from quack_norris.core.llm import Param, Tool, ToolResult, tool
from quack_norris.skills_and_agents.skill_discovery import find_skill_path, load_skill_content


def make_skill_invoke_tool(project_root: Path | None = None) -> Tool:
    @tool(truncation_allowed=False)
    def use_skill(
        name: Annotated[str, Param("Skill name to load")],
    ) -> ToolResult:
        skill_path = find_skill_path(name, project_root)
        content = load_skill_content(name, project_root)
        if skill_path is None or content is None:
            return ToolResult(content=f"Skill '{name}' not found.", is_error=True)
        display_path = skill_path
        if project_root is not None and skill_path.is_relative_to(project_root):
            display_path = skill_path.relative_to(project_root)
        return ToolResult(
            content=f"# Skill: {name}\n\nSkill-Path: {display_path.as_posix()}\n\n{content}"
        )

    return use_skill
