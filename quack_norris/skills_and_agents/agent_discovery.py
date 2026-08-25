from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_GLOBAL_ROOT = Path.home() / ".agents"
_WELL_KNOWN_AGENTS = [
    (".github/copilot-instructions.md", "Github Default"),
    ("CLAUDE.md", "Claude Default"),
    (".cursor/rules", "Cursor Default"),
    (".cursorrules", "Cursor Default"),
]


@dataclass(frozen=True)
class AgentInfo:
    name: str
    path: Path


def _project_agents_dir(project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    directory = project_root / ".agents" / "agents"
    return directory if directory.is_dir() else None


def _well_known_agents(project_root: Path | None) -> dict[str, Path]:
    if project_root is None:
        return {}
    found: dict[str, Path] = {}
    for relative_path, display_name in _WELL_KNOWN_AGENTS:
        path = project_root / relative_path
        if path.exists() and display_name not in found:
            found[display_name] = path
    github_agents = project_root / ".github" / "agents"
    if github_agents.is_dir():
        for path in sorted(github_agents.glob("*.md")):
            found.setdefault(f"Github: {path.stem}", path)
    return found


def discover_agent_info(project_root: Path | None = None) -> list[AgentInfo]:
    found: dict[str, Path] = {}
    for directory in (_GLOBAL_ROOT / "agents", _project_agents_dir(project_root)):
        if directory is None or not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.agent.md")):
            found[path.stem.removesuffix(".agent")] = path
    found.update(_well_known_agents(project_root))
    return [AgentInfo(name, found[name]) for name in sorted(found, key=str.casefold)]


def discover_agents(project_root: Path | None = None) -> list[str]:
    return [agent.name for agent in discover_agent_info(project_root)]


def load_agent_system_prompt(name: str, project_root: Path | None = None) -> str:
    matches = {agent.name: agent.path for agent in discover_agent_info(project_root)}
    path = matches.get(name)
    if path is None:
        raise KeyError(f"Agent '{name}' not found")
    return _strip_frontmatter(path.read_text(encoding="utf-8", errors="replace"))


def _strip_frontmatter(content: str) -> str:
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[end + 3:].lstrip("\n")
    return content
