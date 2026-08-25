from __future__ import annotations

from quack_norris.skills_and_agents import (
    discover_agents,
    discover_skill_info,
    load_agent_system_prompt,
    skill_discovery,
)


def test_project_agent_discovery_and_prompt_loading(tmp_path) -> None:
    agents_dir = tmp_path / ".agents" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "reviewer.agent.md").write_text(
        "---\nname: Reviewer\n---\nReview carefully.\n",
        encoding="utf-8",
    )

    assert "reviewer" in discover_agents(tmp_path)
    assert load_agent_system_prompt("reviewer", tmp_path) == "Review carefully.\n"


def test_skill_info_is_sorted_and_description_is_compact(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(skill_discovery, "_GLOBAL_ROOT", tmp_path / "global")
    skills_dir = tmp_path / ".agents" / "skills"
    for name, content in (
        ("zeta", "Use the fallback description.\n"),
        ("Alpha", "---\ndescription: >\n  First line\n  second line\n---\nBody\n"),
    ):
        directory = skills_dir / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(content, encoding="utf-8")

    skills = discover_skill_info(tmp_path)

    assert [skill.name for skill in skills] == ["Alpha", "zeta"]
    assert skills[0].description == "First line second line"
    assert skills[1].description == "Use the fallback description."
