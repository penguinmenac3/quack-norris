"""upgrade command — upgrade installed skills/agents to latest source commit."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ..cache import current_commit
from ..discovery import find_item_in_repo
from ..manifest import InstalledItem, load_manifest, now_iso, save_manifest
from ..paths import (
    resolve_install_root,
    skill_install_dir,
    tool_agent_dirs,
)
from .update import sync_sources


def _check_one(item: InstalledItem) -> tuple[str | None, str | None]:
    """Compare cached commit to installed commit. Returns (new_commit, error)."""
    new_commit = current_commit(item.source_url) or "unknown"
    if new_commit == item.commit:
        return None, None
    return new_commit, None


def _apply_one(item: InstalledItem, new_commit: str, install_root: Path) -> tuple[bool, str]:
    """Copy updated files for *item*. Returns (success, message)."""
    src_file = find_item_in_repo(item.source_url, item.source_path)
    if src_file is None:
        return False, (
            f"'{item.source_path}' no longer exists in {item.source_url} — "
            "source may have been removed."
        )

    if item.type == "skill":
        dest_skill_dir = skill_install_dir(install_root) / item.local_name
        if dest_skill_dir.exists():
            shutil.rmtree(dest_skill_dir)
        if src_file.name == "SKILL.md":
            shutil.copytree(src_file.parent, dest_skill_dir)
        else:
            dest_skill_dir.mkdir(parents=True)
            shutil.copy2(src_file, dest_skill_dir / "SKILL.md")
    else:
        tool_dirs = tool_agent_dirs(install_root, item.tools)
        for dest_dir in tool_dirs.values():
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest_dir / f"{item.local_name}.agent.md")

    item.commit = new_commit
    item.installed_at = now_iso()
    return True, f"Upgraded {item.type} '{item.local_name}' to {new_commit}"


def cmd_upgrade(args: argparse.Namespace) -> None:
    target: str | None = args.target
    use_global: bool = args.global_
    use_local: bool = getattr(args, "local", False)
    yes: bool = args.yes

    install_root = resolve_install_root(use_global=use_global, use_local=use_local)
    items = load_manifest(install_root)

    if not items:
        print("Nothing installed in this scope.")
        return

    if target is not None:
        if target.endswith(".skill"):
            item_type, local_name = "skill", target[: -len(".skill")]
            matched = [i for i in items if i.type == item_type and i.local_name == local_name]
        elif target.endswith(".agent"):
            item_type, local_name = "agent", target[: -len(".agent")]
            matched = [i for i in items if i.type == item_type and i.local_name == local_name]
        else:
            matched = [i for i in items if i.local_name == target]
            if len(matched) > 1:
                suggestions = "\n".join(f"  quack-norris-manage upgrade {target}.{i.type}" for i in matched)
                print(
                    f"error: '{target}' is ambiguous. Disambiguate with a suffix:\n{suggestions}",
                    file=sys.stderr,
                )
                sys.exit(1)
        if not matched:
            print(f"error: '{target}' is not installed.", file=sys.stderr)
            sys.exit(1)
        candidates = matched
    else:
        candidates = items

    sync_sources()
    print("Checking for updates...")
    pending: list[tuple[InstalledItem, str]] = []

    for item in candidates:
        new_commit, _ = _check_one(item)
        if new_commit is not None:
            pending.append((item, new_commit))

    if not pending:
        print("Everything is already up to date.")
        return

    print(f"\nThe following {len(pending)} item(s) will be upgraded:")
    for item, new_commit in pending:
        print(f"  {item.type:6}  {item.local_name}  {item.commit} → {new_commit}")

    if not yes:
        try:
            answer = input("\nDo you want to upgrade? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if answer not in ("", "y", "yes"):
            print("Aborted.")
            return

    errors: list[str] = []
    upgraded = 0
    for item, new_commit in pending:
        success, message = _apply_one(item, new_commit, install_root)
        if success:
            upgraded += 1
            print(f"  ✓ {message}")
        else:
            print(f"  ✗ {message}", file=sys.stderr)
            errors.append(item.local_name)

    save_manifest(install_root, items)

    parts = [f"{upgraded} upgraded"]
    if errors:
        parts.append(f"{len(errors)} failed")
    print(f"\n{', '.join(parts)}.")

    if errors:
        sys.exit(1)
