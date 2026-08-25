"""source add / remove / list commands."""

from __future__ import annotations

import argparse
import sys

from ..cache import fetch
from ..paths import find_project_root, global_agents_dir
from ..sources import add_source, all_source_entries, remove_source


def _fetch(url: str) -> None:
    print(f"Fetching {url}...")
    ok, msg = fetch(url)
    if ok:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}", file=sys.stderr)


def cmd_source_add(args: argparse.Namespace) -> None:
    urls: list[str] = args.url
    scope: str = args.scope  # "global" or "project"
    agents_dir_override: str | None = args.agents_dir
    skills_dir_override: str | None = args.skills_dir

    def _report(result: str, url: str, label: str) -> None:
        if result == "added":
            print(f"Added source to {label} sources: {url}")
            _fetch(url)
        elif result == "updated":
            print(f"Updated source overrides in {label} sources: {url}")
        else:
            print(f"Source already in {label} sources: {url}")

    if scope == "global":
        agents_dir = global_agents_dir()
        for url in urls:
            result = add_source(agents_dir, url, agents_dir_override, skills_dir_override)
            _report(result, url, "global")
    else:
        project_root = find_project_root()
        if project_root is None:
            print(
                "error: no project root found. Use --local from within a project.",
                file=sys.stderr,
            )
            sys.exit(1)
        agents_dir = project_root / ".agents"
        for url in urls:
            result = add_source(agents_dir, url, agents_dir_override, skills_dir_override)
            _report(result, url, f"project ({project_root})")


def cmd_source_remove(args: argparse.Namespace) -> None:
    urls: list[str] = args.url
    scope: str = args.scope

    if scope == "global":
        agents_dir = global_agents_dir()
        errors = 0
        for url in urls:
            removed = remove_source(agents_dir, url)
            if removed:
                print(f"Removed source from global sources: {url}")
            else:
                print(f"Source not found in global sources: {url}", file=sys.stderr)
                errors += 1
        if errors:
            sys.exit(1)
    else:
        project_root = find_project_root()
        if project_root is None:
            print(
                "error: no project root found. Use --global to remove from global sources.",
                file=sys.stderr,
            )
            sys.exit(1)
        agents_dir = project_root / ".agents"
        errors = 0
        for url in urls:
            removed = remove_source(agents_dir, url)
            if removed:
                print(f"Removed source from project sources ({project_root}): {url}")
            else:
                print(f"Source not found in project sources: {url}", file=sys.stderr)
                errors += 1
        if errors:
            sys.exit(1)


def cmd_source_list(args: argparse.Namespace) -> None:
    project_root = find_project_root()
    entries = all_source_entries(global_agents_dir(), project_root)
    if not entries:
        print("No sources registered. Use `quack-norris-manage source add <url>` to add one.")
        return
    for entry in entries:
        overrides = []
        if entry.agents_dir:
            overrides.append(f"agents-dir: {entry.agents_dir}")
        if entry.skills_dir:
            overrides.append(f"skills-dir: {entry.skills_dir}")
        suffix = f"  ({', '.join(overrides)})" if overrides else ""
        print(f"{entry.url}{suffix}")
