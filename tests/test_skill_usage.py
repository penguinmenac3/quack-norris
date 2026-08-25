from __future__ import annotations

import pytest

from quack_norris.skills_and_agents import make_skill_invoke_tool


@pytest.mark.asyncio
async def test_use_skill_returns_formatted_skill_result(tmp_path) -> None:
    skill_dir = tmp_path / ".agents" / "skills" / "testing"
    skill_dir.mkdir(parents=True)
    skill_content = "Use this testing workflow."
    (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

    use_skill = make_skill_invoke_tool(tmp_path)
    result = await use_skill.execute(name="testing")

    assert result.content == (
        "# Skill: testing\n\nSkill-Path: .agents/skills/testing\n\n"
        f"{skill_content}"
    )


@pytest.mark.asyncio
async def test_use_skill_reports_missing_skill() -> None:
    use_skill = make_skill_invoke_tool()
    result = await use_skill.execute(name="missing")

    assert result.is_error is True
    assert "Skill 'missing' not found" in result.content
