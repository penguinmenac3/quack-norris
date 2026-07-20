"""source add / remove / list commands."""

from __future__ import annotations

import argparse
import sys

from ..cache import fetch
from ..paths import find_project_root, global_agents_dir
from ..sources import add_source, all_sources, load_sources, remove_source


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

    if scope == "global":
        agents_dir = global_agents_dir()
        for url in urls:
            added = add_source(agents_dir, url)
            if added:
                print(f"Added source to global sources: {url}")
                _fetch(url)
            else:
                print(f"Source already in global sources: {url}")
    else:
        project_root = find_project_root()
        if project_root is None:
            print(
                "error: no project root found. Use --global to add to global sources.",
                file=sys.stderr,
            )
            sys.exit(1)
        agents_dir = project_root / ".agents"
        for url in urls:
            added = add_source(agents_dir, url)
            if added:
                print(f"Added source to project sources ({project_root}): {url}")
                _fetch(url)
            else:
                print(f"Source already in project sources: {url}")


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
    sources = all_sources(global_agents_dir(), project_root)
    if not sources:
        print("No sources registered. Use `quack-norris-manage source add <url>` to add one.")
        return
    for url in sources:
        print(url)
