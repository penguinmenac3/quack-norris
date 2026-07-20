"""Scan cached repos to discover available skills and agents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .cache import cache_path


@dataclass
class DiscoveredItem:
    type: str  # "skill" or "agent"
    source_path: str  # path within repo without extension (e.g. "github/foobar")
    source_url: str
    name: str  # description from frontmatter, or empty string
    raw_description: str


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from a Markdown file."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}
    try:
        return yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}


def _relative_source_path(repo_root: Path, file_path: Path) -> str:
    """Return the path relative to repo root without file extension."""
    rel = file_path.relative_to(repo_root)
    parts = list(rel.parts)
    parts[-1] = rel.stem  # strip extension
    return "/".join(parts)


def _in_hidden_dir(repo: Path, f: Path) -> bool:
    """Return True if any path component between repo root and *f* starts with '.'."""
    return any(part.startswith(".") for part in f.relative_to(repo).parts[:-1])


def _collect_files(repo: Path, globs: list[str]) -> list[tuple[Path, str]]:
    """Return (file, source_path) for every matching file outside hidden dirs."""
    results: list[tuple[Path, str]] = []
    for glob in globs:
        for f in repo.rglob(glob):
            if _in_hidden_dir(repo, f):
                continue
            if f.stem == f.stem.upper():
                # Named marker file (e.g. SKILL.md) — identity is the parent directory
                sp = _relative_source_path(repo, f.parent) if f.parent != repo else f.stem
            else:
                # Dotted pattern (e.g. ponytail.skill.md) — strip the type segment
                sp = _relative_source_path(repo, f)
                sp = sp.rsplit(".", 1)[0]
            results.append((f, sp))
    return results


def _skill_files(repo: Path) -> list[tuple[Path, str]]:
    return _collect_files(repo, ["SKILL.md", "*.skill.md"])


def _agent_files(repo: Path) -> list[tuple[Path, str]]:
    return _collect_files(repo, ["*.agent.md"])


def scan_repo(url: str) -> list[DiscoveredItem]:
    """Return all skills and agents found in the cached repo for *url*."""
    repo = cache_path(url)
    if not repo.exists():
        return []

    items: list[DiscoveredItem] = []

    for skill_file, source_path in _skill_files(repo):
        text = skill_file.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        items.append(
            DiscoveredItem(
                type="skill",
                source_path=source_path,
                source_url=url,
                name=fm.get("name", source_path.split("/")[-1]),
                raw_description=str(fm.get("description", "")).strip(),
            )
        )

    for agent_file, source_path in _agent_files(repo):
        text = agent_file.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        items.append(
            DiscoveredItem(
                type="agent",
                source_path=source_path,
                source_url=url,
                name=fm.get("name", source_path.split("/")[-1]),
                raw_description=str(fm.get("description", "")).strip(),
            )
        )

    return items


def scan_all(source_urls: list[str]) -> list[DiscoveredItem]:
    """Scan all cached repos and return every discovered item."""
    items: list[DiscoveredItem] = []
    for url in source_urls:
        items.extend(scan_repo(url))
    return items


def find_item_in_repo(url: str, source_path: str) -> Path | None:
    """Locate the actual file for *source_path* in the cached repo for *url*.

    *source_path* is without extension (e.g. "skills/ponytail" or "github/foobar").
    Tries all recognised naming patterns.
    """
    repo = cache_path(url)

    candidates = [
        repo / (source_path + ".skill.md"),
        repo / (source_path + ".agent.md"),
        repo / source_path / "SKILL.md",
        repo / source_path / "AGENTS.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
