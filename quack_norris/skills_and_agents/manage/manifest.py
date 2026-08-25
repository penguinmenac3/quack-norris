"""installed.yaml read/write — tracks what was installed where."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml

_MANIFEST_FILENAME = "installed.yaml"
_VERSION = 1


@dataclass
class InstalledItem:
    type: Literal["skill", "agent"]
    local_name: str
    source_url: str
    source_path: str
    commit: str
    installed_at: str
    tools: list[str] = field(default_factory=list)  # agents only

    def to_dict(self) -> dict:
        d: dict = {
            "type": self.type,
            "local_name": self.local_name,
            "source_url": self.source_url,
            "source_path": self.source_path,
            "commit": self.commit,
            "installed_at": self.installed_at,
        }
        if self.type == "agent":
            d["tools"] = self.tools
        return d

    @staticmethod
    def from_dict(d: dict) -> "InstalledItem":
        return InstalledItem(
            type=d["type"],
            local_name=d["local_name"],
            source_url=d["source_url"],
            source_path=d["source_path"],
            commit=d["commit"],
            installed_at=d["installed_at"],
            tools=d.get("tools", []),
        )


def _manifest_path(install_root: Path) -> Path:
    return install_root / ".agents" / _MANIFEST_FILENAME


def load_manifest(install_root: Path) -> list[InstalledItem]:
    path = _manifest_path(install_root)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [InstalledItem.from_dict(item) for item in data.get("installed", [])]


def save_manifest(install_root: Path, items: list[InstalledItem]) -> None:
    path = _manifest_path(install_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"version": _VERSION, "installed": [i.to_dict() for i in items]},
            f,
            default_flow_style=False,
        )


def find_item(
    items: list[InstalledItem], *, item_type: str, local_name: str
) -> InstalledItem | None:
    for item in items:
        if item.type == item_type and item.local_name == local_name:
            return item
    return None


def add_item(install_root: Path, item: InstalledItem) -> None:
    items = load_manifest(install_root)
    items = [i for i in items if not (i.type == item.type and i.local_name == item.local_name)]
    items.append(item)
    save_manifest(install_root, items)


def remove_item(install_root: Path, *, item_type: str, local_name: str) -> bool:
    items = load_manifest(install_root)
    new_items = [i for i in items if not (i.type == item_type and i.local_name == local_name)]
    if len(new_items) == len(items):
        return False
    save_manifest(install_root, new_items)
    return True


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
