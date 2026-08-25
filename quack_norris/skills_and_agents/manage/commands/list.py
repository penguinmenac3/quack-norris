"""list command — show available skills and agents across all sources."""

from __future__ import annotations

import argparse

from ..discovery import DiscoveredItem, scan_all
from ..manifest import InstalledItem, load_manifest
from ..paths import find_project_root, global_agents_dir, resolve_install_root
from ..sources import all_source_entries
from .update import sync_sources


def _installed_label(item: DiscoveredItem, installed: list[InstalledItem]) -> str | None:
    """Return the installed label string, or None if not installed."""
    for inst in installed:
        if inst.type == item.type and inst.source_url == item.source_url and inst.source_path == item.source_path:
            if inst.local_name != item.source_path.split("/")[-1]:
                return f"installed as {inst.local_name}"
            return "installed"
    return None


def _collect_installed(use_global: bool, use_local: bool) -> list[InstalledItem]:
    install_root = resolve_install_root(use_global=use_global, use_local=use_local)
    return load_manifest(install_root)


def _all_installed_with_scope(use_global: bool, use_local: bool) -> list[tuple[InstalledItem, str]]:
    """Return (item, scope_label) for every installed item across relevant scopes."""
    from pathlib import Path

    results: list[tuple[InstalledItem, str]] = []

    if use_global:
        for item in load_manifest(global_agents_dir()):
            results.append((item, "global"))
        return results

    if use_local:
        local_root = resolve_install_root(use_global=False, use_local=True)
        for item in load_manifest(local_root):
            results.append((item, "local"))
        return results

    # Default: check global + project + local, skip duplicate roots
    seen_roots: set[Path] = set()
    for scope_label, root in [
        ("global", global_agents_dir()),
        ("project", find_project_root()),
        ("local", Path.cwd()),
    ]:
        if root is None:
            continue
        resolved = root.resolve()
        if resolved in seen_roots:
            continue
        seen_roots.add(resolved)
        for item in load_manifest(root):
            results.append((item, scope_label))

    return results


def _print_installed_only(use_global: bool, use_local: bool) -> None:
    from collections import defaultdict
    tagged = _all_installed_with_scope(use_global, use_local)

    # Group by (type, local_name, source_path) → list of (scope, commit, tools)
    groups: dict[tuple[str, str, str], list[tuple[str, str, list[str]]]] = defaultdict(list)
    for item, scope in tagged:
        groups[(item.type, item.local_name, item.source_path)].append((scope, item.commit, item.tools))

    def render(item_type: str) -> list[str]:
        lines = []
        for (itype, local_name, source_path), entries in sorted(groups.items(), key=lambda x: x[0][1]):
            if itype != item_type:
                continue
            scope_str = ", ".join(f"{s}: {c}" for s, c, _ in entries)
            tools = entries[0][2]
            tools_str = f" [{', '.join(tools)}]" if tools else ""
            lines.append(f"* {local_name}  ({source_path} @ {scope_str}){tools_str}")
        return lines

    def print_section(title: str, item_type: str) -> None:
        lines = render(item_type)
        print(f"{title}:")
        if not lines:
            print("  (none)")
            return
        for line in lines:
            print(line)

    print_section("Skills", "skill")
    print()
    print_section("Agents", "agent")


def cmd_list(args: argparse.Namespace) -> None:
    use_global: bool = args.global_
    use_local: bool = getattr(args, "local", False)
    details: bool = args.details
    installed_only: bool = args.installed

    if installed_only:
        _print_installed_only(use_global, use_local)
        return

    installed = _collect_installed(use_global, use_local)

    sync_sources()

    project_root = find_project_root()
    sources = all_source_entries(global_agents_dir(), project_root)
    all_items = scan_all(sources)

    skills = [i for i in all_items if i.type == "skill"]
    agents = [i for i in all_items if i.type == "agent"]

    def sort_key(item: DiscoveredItem) -> tuple:
        label = _installed_label(item, installed)
        return (0 if label else 1, item.source_path)

    skills.sort(key=sort_key)
    agents.sort(key=sort_key)

    def print_section(title: str, items: list[DiscoveredItem]) -> None:
        print(f"{title}:")
        if not items:
            print("  (none)")
            return
        for item in items:
            label = _installed_label(item, installed)
            label_str = f" [{label}]" if label else ""
            print(f"* {item.source_path} ({item.source_url}){label_str}")
            if details and item.raw_description:
                for line in item.raw_description.splitlines():
                    print(f"    {line}")
                print()

    print_section("Skills", skills)
    print()
    print_section("Agents", agents)
