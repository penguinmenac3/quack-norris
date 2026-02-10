from typing import NamedTuple, Optional


class Skill(NamedTuple):
    description: str
    tools: list[str]
    prompt: str


# Registry
_skills: dict[str, Skill] = {}


def list_skills(names_or_partials: list[str] | None = None) -> dict[str, Skill]:
    """List all skills in the registry."""
    if names_or_partials is None:
        return _skills
    return {name: _skills[name] for name in names_or_partials if name in _skills}


def get_skill(name: str) -> Optional[Skill]:
    """Retrieve a skill by name."""
    return _skills.get(name)


def find_skill(query: str, skills: dict[str, Skill]) -> Optional[Skill]:
    """Find a skill by name or description matching the query."""
    query_lower = query.lower()
    for name, skill in skills.items():
        if query_lower in name.lower() or query_lower in skill.description.lower():
            return skill
    return None


def update_skill(name: str, skill: Skill):
    """Update or add a skill to the registry."""
    _skills[name] = skill


def remove_skill(name: str):
    """Remove a skill from the registry."""
    del _skills[name]
