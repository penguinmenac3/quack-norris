"""Shared helper: fetch/update all registered source repos."""

from __future__ import annotations

import sys

from ..cache import fetch, is_cached
from ..paths import find_project_root, global_agents_dir
from ..sources import all_sources


def sync_sources(silent_if_cached: bool = True) -> list[str]:
    """Fetch all registered sources. Returns list of URLs that failed.

    If *silent_if_cached* is True, already-cached repos are fetched silently
    (no output). New repos (first clone) always print progress.
    """
    project_root = find_project_root()
    sources = all_sources(global_agents_dir(), project_root)
    errors: list[str] = []

    for url in sources:
        first_clone = not is_cached(url)
        if first_clone:
            print(f"Fetching {url}...")
        ok, message = fetch(url)
        if not ok:
            if first_clone:
                print(f"  ✗ {message}", file=sys.stderr)
                errors.append(url)
            else:
                print(f"  (offline, using cached version of {url})", file=sys.stderr)
        elif first_clone:
            print(f"  ✓ {message}")

    return errors
