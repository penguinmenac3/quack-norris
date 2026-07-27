"""Tests for skill loading through the quack tool result."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from quack_norris.tools.quack import QuackContext, make_quack_tools


@pytest.mark.asyncio
async def test_use_skill_returns_formatted_skill_result(tmp_path) -> None:
    skill_dir = tmp_path / ".agents" / "skills" / "testing"
    skill_dir.mkdir(parents=True)
    skill_content = "Use this testing workflow."
    (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

    ctx = QuackContext(
        session_id="test-session",
        meta=SimpleNamespace(cwd=str(tmp_path)),
        system_prompt_parts=[],
        prompt_ref=["base prompt"],
        ask_user_fn=None,
    )
    use_skill = next(tool for tool in make_quack_tools(ctx) if tool.name == "use_skill")

    result = await use_skill.execute(name="testing")

    assert result.content == (
        "# Skill: testing\n\nSkill-Path: .agents\\skills\\testing\n\n"
        f"{skill_content}"
    )
    assert ctx.system_prompt_parts == []


@pytest.mark.asyncio
async def test_use_skill_reports_missing_skill() -> None:
    ctx = QuackContext(
        session_id="test-session",
        meta=SimpleNamespace(cwd=None),
        system_prompt_parts=[],
        prompt_ref=["base prompt"],
        ask_user_fn=None,
    )
    use_skill = next(tool for tool in make_quack_tools(ctx) if tool.name == "use_skill")

    result = await use_skill.execute(name="missing")

    assert result.is_error is True
    assert "Skill 'missing' not found" in result.content
