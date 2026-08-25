"""sources.yaml read/write for global and project-level source lists."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_SOURCES_FILENAME = "sources.yaml"
_VERSION = 1


@dataclass
class SourceEntry:
    url: str
    agents_dir: str | None = None
    skills_dir: str | None = None


def _entry_from_raw(raw: str | dict) -> SourceEntry:
    if isinstance(raw, str):
        return SourceEntry(url=raw)
    return SourceEntry(
        url=raw["url"],
        agents_dir=raw.get("agents_dir"),
        skills_dir=raw.get("skills_dir"),
    )


def _entry_to_raw(entry: SourceEntry) -> str | dict:
    if entry.agents_dir is None and entry.skills_dir is None:
        return entry.url
    raw: dict = {"url": entry.url}
    if entry.agents_dir is not None:
        raw["agents_dir"] = entry.agents_dir
    if entry.skills_dir is not None:
        raw["skills_dir"] = entry.skills_dir
    return raw


def _load_raw(path: Path) -> list[SourceEntry]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [_entry_from_raw(raw) for raw in data.get("sources", [])]


def _save_raw(path: Path, entries: list[SourceEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"version": _VERSION, "sources": [_entry_to_raw(e) for e in entries]},
            f,
            default_flow_style=False,
        )


def sources_path(agents_dir: Path) -> Path:
    return agents_dir / ".agents" / _SOURCES_FILENAME


def load_source_entries(agents_dir: Path) -> list[SourceEntry]:
    """Load the list of source entries from *agents_dir*/sources.yaml."""
    return _load_raw(sources_path(agents_dir))


def load_sources(agents_dir: Path) -> list[str]:
    """Load the list of source URLs from *agents_dir*/sources.yaml."""
    return [e.url for e in load_source_entries(agents_dir)]


def save_sources(agents_dir: Path, entries: list[SourceEntry]) -> None:
    """Write *entries* to *agents_dir*/sources.yaml."""
    _save_raw(sources_path(agents_dir), entries)


def add_source(
    agents_dir: Path,
    url: str,
    agents_dir_override: str | None = None,
    skills_dir_override: str | None = None,
) -> str:
    """Add *url* to sources.yaml, or update its dir overrides if already present.

    Returns "added" for a new source, "updated" if it existed and its dir
    overrides were changed, or "unchanged" if it existed with no changes.
    """
    entries = load_source_entries(agents_dir)
    for entry in entries:
        if entry.url == url:
            changed = False
            if agents_dir_override is not None and entry.agents_dir != agents_dir_override:
                entry.agents_dir = agents_dir_override
                changed = True
            if skills_dir_override is not None and entry.skills_dir != skills_dir_override:
                entry.skills_dir = skills_dir_override
                changed = True
            if changed:
                save_sources(agents_dir, entries)
                return "updated"
            return "unchanged"
    entries.append(
        SourceEntry(url=url, agents_dir=agents_dir_override, skills_dir=skills_dir_override)
    )
    save_sources(agents_dir, entries)
    return "added"


def remove_source(agents_dir: Path, url: str) -> bool:
    """Remove *url* from sources.yaml. Returns True if removed, False if not found."""
    entries = load_source_entries(agents_dir)
    remaining = [e for e in entries if e.url != url]
    if len(remaining) == len(entries):
        return False
    save_sources(agents_dir, remaining)
    return True


def all_sources(global_agents_dir: Path, project_root: Path | None) -> list[str]:
    """Return deduplicated list of all source URLs from global + project sources."""
    return [e.url for e in all_source_entries(global_agents_dir, project_root)]


def all_source_entries(
    global_agents_dir: Path, project_root: Path | None
) -> list[SourceEntry]:
    """Return deduplicated list of all source entries from global + project sources."""
    seen: set[str] = set()
    result: list[SourceEntry] = []
    for entry in load_source_entries(global_agents_dir):
        if entry.url not in seen:
            seen.add(entry.url)
            result.append(entry)
    if project_root is not None:
        for entry in load_source_entries(project_root / ".agents"):
            if entry.url not in seen:
                seen.add(entry.url)
                result.append(entry)
    return result
