"""Agent and skill discovery helpers.

Scans well-known directories for .agent.md files and SKILL.md directories.
Paths match what quack-norris-manage installs:

Agents:
  Global:  ~/.agents/agents/*.agent.md
  Project: <project-root>/.agents/agents/*.agent.md

Also detects well-known IDE instruction files at the project root:
  .github/copilot-instructions.md  → "Github Default"
  .github/agents/*.md              → "Github: <name>"
  CLAUDE.md                        → "Claude Default"
  .cursor/rules                    → "Cursor Default"
  .cursorrules                     → "Cursor Default"

Skills:
  Global:  ~/.agents/skills/<name>/SKILL.md
  Project: <project-root>/.agents/skills/<name>/SKILL.md
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Global install root used by quack-norris-manage
_GLOBAL_ROOT = Path.home() / ".agents"


def _global_agents_dir() -> Path:
    return _GLOBAL_ROOT / "agents"


def _global_skills_dir() -> Path:
    return _GLOBAL_ROOT / "skills"


def _project_agents_dir(project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    d = project_root / ".agents" / "agents"
    return d if d.is_dir() else None


def _project_skills_dir(project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    d = project_root / ".agents" / "skills"
    return d if d.is_dir() else None


# ---------------------------------------------------------------------------
# Well-known IDE instruction files
# ---------------------------------------------------------------------------

# Each entry: (relative path from project root, display name)
# Order matters: first match wins for a given display name.
_WELL_KNOWN_AGENTS: list[tuple[str, str]] = [
    (".github/copilot-instructions.md", "Github Default"),
    ("CLAUDE.md", "Claude Default"),
    (".cursor/rules", "Cursor Default"),
    (".cursorrules", "Cursor Default"),
]


def _well_known_agents(project_root: Path | None) -> dict[str, Path]:
    """Return display-name → path for well-known IDE instruction files present in project_root."""
    if project_root is None:
        return {}
    found: dict[str, Path] = {}
    for rel, display_name in _WELL_KNOWN_AGENTS:
        p = project_root / rel
        if p.exists() and display_name not in found:
            found[display_name] = p
    # Also scan .github/agents/*.md as "Github: <name>"
    github_agents_dir = project_root / ".github" / "agents"
    if github_agents_dir.is_dir():
        for f in sorted(github_agents_dir.glob("*.md")):
            display_name = f"Github: {f.stem}"
            found.setdefault(display_name, f)
    return found


# ---------------------------------------------------------------------------
# Agent discovery
# ---------------------------------------------------------------------------

def discover_agents(project_root: Path | None = None) -> list[str]:
    """Return sorted list of agent names available."""
    names: dict[str, Path] = {}

    def _scan(directory: Path | None) -> None:
        if directory is None or not directory.is_dir():
            return
        for f in sorted(directory.glob("*.agent.md")):
            name = f.stem.removesuffix(".agent")
            names[name] = f

    _scan(_global_agents_dir())
    _scan(_project_agents_dir(project_root))
    names.update(_well_known_agents(project_root))

    return sorted(names)


def load_agent_system_prompt(name: str, project_root: Path | None = None) -> str:
    """Load system prompt from a named agent file. Returns default prompt if not found."""
    # Check well-known IDE files first
    well_known = _well_known_agents(project_root)
    if name in well_known:
        content = well_known[name].read_text(encoding="utf-8", errors="replace")
        return _strip_frontmatter(content)

    candidates: list[Path] = []
    for d in [_project_agents_dir(project_root), _global_agents_dir()]:
        if d and d.is_dir():
            for f in d.glob("*.agent.md"):
                agent_name = f.stem.removesuffix(".agent")
                if agent_name == name:
                    candidates.append(f)

    if not candidates:
        return f"You are {name}, a helpful AI assistant."

    content = candidates[0].read_text(encoding="utf-8", errors="replace")
    return _strip_frontmatter(content)


# ---------------------------------------------------------------------------
# Skill discovery
# ---------------------------------------------------------------------------

def discover_skills(project_root: Path | None = None) -> list[str]:
    """Return sorted list of skill names available."""
    names: dict[str, Path] = {}

    def _scan(directory: Path | None) -> None:
        if directory is None or not directory.is_dir():
            return
        for d in sorted(directory.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                names[d.name] = d / "SKILL.md"

    _scan(_global_skills_dir())
    _scan(_project_skills_dir(project_root))

    return sorted(names)


def load_skill_content(name: str, project_root: Path | None = None) -> str | None:
    """Load skill content by name. Returns None if not found."""
    for d in [_project_skills_dir(project_root), _global_skills_dir()]:
        if d and d.is_dir():
            skill_file = d / name / "SKILL.md"
            if skill_file.exists():
                return skill_file.read_text(encoding="utf-8", errors="replace")
    return None


def load_skill_description(name: str, project_root: Path | None = None, max_chars: int = 1000) -> str:
    """Return a short description for a skill from its SKILL.md.

    Tries the YAML frontmatter ``description:`` field first, then falls back
    to the first non-empty, non-heading line after stripping frontmatter.
    Truncates to *max_chars* with an ellipsis if longer.
    """
    content = load_skill_content(name, project_root)
    if not content:
        return ""
    desc = ""
    # Try frontmatter description: field
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            frontmatter = content[3:end]
            lines = frontmatter.splitlines()
            for i, line in enumerate(lines):
                if line.lower().startswith("description:"):
                    value = line.split(":", 1)[1].strip()
                    if value in (">", "|", ">-", "|-", ">+", "|+"):
                        # Block scalar — collect indented continuation lines
                        block_lines = []
                        for cont in lines[i + 1:]:
                            if cont and (cont[0] == " " or cont[0] == "\t"):
                                block_lines.append(cont.strip())
                            else:
                                break
                        desc = " ".join(block_lines)
                    else:
                        desc = value.strip('"').strip("'")
                    break
    # Fall back to first non-empty, non-heading line of the body
    if not desc:
        body = _strip_frontmatter(content)
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                desc = stripped
                break
    if len(desc) > max_chars:
        desc = desc[:max_chars] + "..."
    return desc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_frontmatter(content: str) -> str:
    """Strip YAML frontmatter (--- ... ---) from markdown content."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[end + 3:].lstrip("\n")
    return content
