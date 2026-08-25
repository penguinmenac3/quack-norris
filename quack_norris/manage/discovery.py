"""Scan cached repos to discover available skills and agents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .cache import cache_path
from .sources import SourceEntry


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


def _collect_files(
    root: Path, repo: Path, globs: list[str], skip_hidden: bool = True
) -> list[tuple[Path, str]]:
    """Return (file, source_path) for every matching file under *root*.

    *source_path* is always computed relative to *repo* (the repo root), even
    when *root* is a subdirectory of it. When *skip_hidden* is True, files
    inside dot-prefixed directories (relative to *repo*) are excluded.
    """
    results: list[tuple[Path, str]] = []
    if not root.exists():
        return results
    for glob in globs:
        for f in root.rglob(glob):
            if skip_hidden and _in_hidden_dir(repo, f):
                continue
            if f.stem == f.stem.upper():
                # Named marker file (e.g. SKILL.md) — identity is the parent directory
                sp = _relative_source_path(repo, f.parent) if f.parent != repo else f.stem
            else:
                # Dotted pattern (e.g. ponytail.skill.md) — strip the type segment
                # from the filename only (a dot in an ancestor dir, e.g.
                # ".opencode/...", must not be mistaken for it).
                rel = f.relative_to(repo)
                parts = list(rel.parts)
                parts[-1] = rel.stem.rsplit(".", 1)[0] if "." in rel.stem else rel.stem
                sp = "/".join(parts)
            results.append((f, sp))
    return results


def _skill_files(repo: Path, skills_dir: str | None) -> list[tuple[Path, str]]:
    results = _collect_files(repo, repo, ["SKILL.md", "*.skill.md"])
    if skills_dir:
        explicit = _collect_files(repo / skills_dir, repo, ["SKILL.md", "*.skill.md"], skip_hidden=False)
        seen = {sp for _, sp in results}
        results.extend((f, sp) for f, sp in explicit if sp not in seen)
    return results


def _agent_files(repo: Path, agents_dir: str | None) -> list[tuple[Path, str]]:
    results = _collect_files(repo, repo, ["*.agent.md"])
    if agents_dir:
        # An explicit agents_dir is a directory the user has told us contains
        # only agents, so accept any *.md file (not just the *.agent.md
        # naming convention — some tools, e.g. opencode, use plain names).
        explicit = _collect_files(repo / agents_dir, repo, ["*.md"], skip_hidden=False)
        seen = {sp for _, sp in results}
        results.extend((f, sp) for f, sp in explicit if sp not in seen)
    return results


def scan_repo(entry: SourceEntry) -> list[DiscoveredItem]:
    """Return all skills and agents found in the cached repo for *entry*."""
    url = entry.url
    repo = cache_path(url)
    if not repo.exists():
        return []

    items: list[DiscoveredItem] = []

    for skill_file, source_path in _skill_files(repo, entry.skills_dir):
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

    for agent_file, source_path in _agent_files(repo, entry.agents_dir):
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


def scan_all(entries: list[SourceEntry]) -> list[DiscoveredItem]:
    """Scan all cached repos and return every discovered item."""
    items: list[DiscoveredItem] = []
    for entry in entries:
        items.extend(scan_repo(entry))
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
        repo / (source_path + ".md"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
