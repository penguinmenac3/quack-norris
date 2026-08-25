"""Project root detection and install path resolution."""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_MARKERS = {
    ".git",
    ".github",
    ".agents",
    ".venv",
    "node_modules",
    "pyproject.toml",
    "package.json",
}

_GLOBAL_AGENTS_DIR = Path.home() / ".agents"
_QUACK_NORRIS_DIR = Path.home() / ".config/quack-norris"


def quack_norris_dir() -> Path:
    """Return ~/.config/quack-norris, creating it if needed."""
    _QUACK_NORRIS_DIR.mkdir(parents=True, exist_ok=True)
    return _QUACK_NORRIS_DIR


def global_agents_dir() -> Path:
    """Return ~/.agents, creating it if needed."""
    _GLOBAL_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    return _GLOBAL_AGENTS_DIR.parent


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk upward from *start* (defaults to CWD) and return the closest
    directory that contains a project marker.

    Returns None if no project root is found, or if the found root resolves
    to the same path as ~/.agents (which is the global install location and
    not a real project).
    """
    current = (start or Path.cwd()).resolve()
    while True:
        for marker in _PROJECT_MARKERS:
            if (current / marker).exists():
                if current.resolve() == _GLOBAL_AGENTS_DIR.resolve():
                    return None
                return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def resolve_install_root(*, use_global: bool, use_local: bool) -> Path:
    """Return the base install root directory based on the requested mode.

    Raises SystemExit with a descriptive message on failure.
    """
    if use_global and use_local:
        _die("--global and --local are mutually exclusive.")

    if use_global:
        d = global_agents_dir() / ".agents"
    elif use_local:
        d = Path.cwd() / ".agents"
    else:
        d = find_project_root()
        if d is None:
            _die(
                "No project root found (looked for .git, .github, .agents, .venv, "
                "pyproject.toml, package.json walking upward from the current directory).\n"
                "Use --global to install globally or --local to install in the current directory."
            )
        d = d / ".agents"
    d.mkdir(parents=True, exist_ok=True)
    return d.parent  # caller appends .agents/skills/ as needed


def skill_install_dir(root: Path) -> Path:
    """Return the skills directory inside *root*, creating it if needed."""
    d = root / ".agents" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tool_agent_dirs(root: Path, tools: list[str]) -> dict[str, Path]:
    """Return a mapping of tool-name → target directory for agent tool flags.

    *root* is the resolved install root (project root, CWD, or ~/.agents parent).
    """
    mapping: dict[str, Path] = {}
    for tool in tools:
        match tool:
            case "quack-norris":
                if root == _GLOBAL_AGENTS_DIR:
                    d = Path.home() / ".agents" / "agents"
                else:
                    d = root / ".agents" / "agents"
                d.mkdir(parents=True, exist_ok=True)
                mapping[tool] = d
            case "copilot":
                if root == _GLOBAL_AGENTS_DIR:
                    d = Path.home() / ".copilot" / "agents"
                else:
                    d = root / ".copilot"
                d.mkdir(parents=True, exist_ok=True)
                mapping[tool] = d
            case "claude":
                if root == _GLOBAL_AGENTS_DIR:
                    d = Path.home() / ".claude" / "agents"
                else:
                    d = root / ".claude" / "agents"
                d.mkdir(parents=True, exist_ok=True)
                mapping[tool] = d
            case "windsurf":
                if root == _GLOBAL_AGENTS_DIR:
                    d = Path.home() / ".windsurf" / "workflows"
                else:
                    d = root / ".windsurf" / "workflows"
                d.mkdir(parents=True, exist_ok=True)
                mapping[tool] = d
            case "continue":
                if root == _GLOBAL_AGENTS_DIR:
                    d = Path.home() / ".continue"
                else:
                    d = root / ".continue"
                d.mkdir(parents=True, exist_ok=True)
                mapping[tool] = d
    return mapping


def manifest_path(install_root: Path) -> Path:
    """Return the path to installed.yaml for the given install root."""
    agents_dir = install_root / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    return agents_dir / "installed.yaml"


def _die(message: str) -> None:
    import sys

    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)
