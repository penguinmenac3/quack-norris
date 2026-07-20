"""sources.yaml read/write for global and project-level source lists."""

from __future__ import annotations

from pathlib import Path

import yaml

_SOURCES_FILENAME = "sources.yaml"
_VERSION = 1


def _load_raw(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("sources", []))


def _save_raw(path: Path, urls: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump({"version": _VERSION, "sources": urls}, f, default_flow_style=False)


def sources_path(agents_dir: Path) -> Path:
    return agents_dir / ".agents" / _SOURCES_FILENAME


def load_sources(agents_dir: Path) -> list[str]:
    """Load the list of source URLs from *agents_dir*/sources.yaml."""
    return _load_raw(sources_path(agents_dir))


def save_sources(agents_dir: Path, urls: list[str]) -> None:
    """Write *urls* to *agents_dir*/sources.yaml."""
    _save_raw(sources_path(agents_dir), urls)


def add_source(agents_dir: Path, url: str) -> bool:
    """Append *url* to sources.yaml. Returns True if added, False if already present."""
    urls = load_sources(agents_dir)
    if url in urls:
        return False
    urls.append(url)
    save_sources(agents_dir, urls)
    return True


def remove_source(agents_dir: Path, url: str) -> bool:
    """Remove *url* from sources.yaml. Returns True if removed, False if not found."""
    urls = load_sources(agents_dir)
    if url not in urls:
        return False
    urls.remove(url)
    save_sources(agents_dir, urls)
    return True


def all_sources(global_agents_dir: Path, project_root: Path | None) -> list[str]:
    """Return deduplicated list of all source URLs from global + project sources."""
    seen: set[str] = set()
    result: list[str] = []
    for url in load_sources(global_agents_dir):
        if url not in seen:
            seen.add(url)
            result.append(url)
    if project_root is not None:
        for url in load_sources(project_root / ".agents"):
            if url not in seen:
                seen.add(url)
                result.append(url)
    return result
