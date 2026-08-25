from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quack_norris.core import SkillInfo

_GLOBAL_ROOT = Path.home() / ".agents"
_MAX_DESCRIPTION_LENGTH = 240


@dataclass(frozen=True)
class DiscoveredSkill:
    info: SkillInfo
    path: Path


def _project_skills_dir(project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    directory = project_root / ".agents" / "skills"
    return directory if directory.is_dir() else None


def discover_skill_records(project_root: Path | None = None) -> list[DiscoveredSkill]:
    found: dict[str, Path] = {}
    for directory in (_GLOBAL_ROOT / "skills", _project_skills_dir(project_root)):
        if directory is None or not directory.is_dir():
            continue
        for skill_dir in sorted(directory.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if skill_dir.is_dir() and skill_file.exists():
                found[skill_dir.name] = skill_file
    return [
        DiscoveredSkill(
            info=SkillInfo(name=name, description=_skill_description(path)),
            path=path,
        )
        for name, path in sorted(found.items(), key=lambda item: item[0].casefold())
    ]


def discover_skill_info(project_root: Path | None = None) -> list[SkillInfo]:
    return [skill.info for skill in discover_skill_records(project_root)]


def discover_skills(project_root: Path | None = None) -> list[str]:
    return [skill.info.name for skill in discover_skill_records(project_root)]


def find_skill_path(name: str, project_root: Path | None = None) -> Path | None:
    for skill in discover_skill_records(project_root):
        if skill.info.name == name:
            return skill.path.parent
    return None


def load_skill_content(name: str, project_root: Path | None = None) -> str | None:
    skill_path = find_skill_path(name, project_root)
    if skill_path is None:
        return None
    return (skill_path / "SKILL.md").read_text(encoding="utf-8", errors="replace")


def _skill_description(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    description = _frontmatter_description(content) or _first_body_line(content)
    normalized = " ".join(description.split())
    if len(normalized) > _MAX_DESCRIPTION_LENGTH:
        return normalized[: _MAX_DESCRIPTION_LENGTH - 3].rstrip() + "..."
    return normalized


def _frontmatter_description(content: str) -> str:
    if not content.startswith("---"):
        return ""
    end = content.find("---", 3)
    if end == -1:
        return ""
    lines = content[3:end].splitlines()
    for index, line in enumerate(lines):
        if not line.lower().startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value in {">", "|", ">-", "|-", ">+", "|+"}:
            block: list[str] = []
            for continuation in lines[index + 1 :]:
                if continuation.startswith((" ", "\t")):
                    block.append(continuation.strip())
                else:
                    break
            return " ".join(block)
        return value.strip('"').strip("'")
    return ""


def _first_body_line(content: str) -> str:
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3 :]
    for line in content.splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            return value
    return ""
