"""uninstall command — remove an installed skill or agent."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ..manifest import InstalledItem, find_item, load_manifest, remove_item
from ..paths import (
    resolve_install_root,
    skill_install_dir,
    tool_agent_dirs,
)


def _resolve_target(
    target: str, items: list[InstalledItem]
) -> tuple[str, str] | None:
    """Return (item_type, local_name) or None on error (error already printed)."""
    if target.endswith(".skill"):
        return "skill", target[: -len(".skill")]
    if target.endswith(".agent"):
        return "agent", target[: -len(".agent")]

    matched = [i for i in items if i.local_name == target]
    if len(matched) == 1:
        return matched[0].type, target
    if len(matched) > 1:
        suggestions = "\n".join(f"  quack-norris-manage uninstall {target}.{i.type}" for i in matched)
        print(
            f"error: '{target}' is ambiguous. Disambiguate with a suffix:\n{suggestions}",
            file=sys.stderr,
        )
        return None
    return "skill", target  # not found — let _uninstall_one produce the error


def _uninstall_one(raw_target: str, install_root: Path) -> bool:
    """Uninstall a single target. Returns True on success, False on error."""
    items = load_manifest(install_root)
    resolved = _resolve_target(raw_target, items)
    if resolved is None:
        return False
    item_type, local_name = resolved

    item = find_item(items, item_type=item_type, local_name=local_name)

    if item is None:
        print(
            f"error: {item_type} '{local_name}' is not installed (not found in manifest).",
            file=sys.stderr,
        )
        return False

    removed_files: list[Path] = []

    if item_type == "skill":
        dest = skill_install_dir(install_root) / local_name
        if dest.exists():
            shutil.rmtree(dest)
            removed_files.append(dest)
    else:
        tool_dirs = tool_agent_dirs(install_root, item.tools)
        for _tool_name, dest_dir in tool_dirs.items():
            dest = dest_dir / f"{local_name}.agent.md"
            if dest.exists():
                dest.unlink()
                removed_files.append(dest)

    remove_item(install_root, item_type=item_type, local_name=local_name)

    if removed_files:
        location = removed_files[0]
        print(f"Uninstalled {item_type} '{local_name}' ← {location}")
    else:
        print(f"Uninstalled {item_type} '{local_name}' (warning: no files found on disk, manifest entry removed).")
    return True


def cmd_uninstall(args: argparse.Namespace) -> None:
    use_global: bool = args.global_
    use_local: bool = getattr(args, "local", False)
    install_root = resolve_install_root(use_global=use_global, use_local=use_local)

    targets: list[str] = args.target
    errors = 0
    for raw_target in targets:
        ok = _uninstall_one(raw_target, install_root)
        if not ok:
            errors += 1

    if errors:
        sys.exit(1)
