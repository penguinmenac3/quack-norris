"""Git cache — clone/fetch source repos into ~/.config/quack-norris/cache/."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from .paths import quack_norris_dir


def _cache_root() -> Path:
    d = quack_norris_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _repo_slug(url: str) -> str:
    """Derive a filesystem-safe directory name from a git URL."""
    slug = re.sub(r"[^\w]", "_", url)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:120]


def cache_path(url: str) -> Path:
    return _cache_root() / _repo_slug(url)


def _require_git() -> None:
    if shutil.which("git") is None:
        print("error: git is required but not found on PATH.", file=sys.stderr)
        sys.exit(1)


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def fetch(url: str) -> tuple[bool, str]:
    """Clone or update the cached repo for *url*.

    Returns (success, message).
    """
    _require_git()
    dest = cache_path(url)

    if dest.exists():
        result = _run(["git", "fetch", "--depth", "1", "origin"], cwd=dest)
        if result.returncode != 0:
            return False, f"git fetch failed for {url}:\n{result.stderr.strip()}"
        result = _run(["git", "reset", "--hard", "origin/HEAD"], cwd=dest)
        if result.returncode != 0:
            return False, f"git reset failed for {url}:\n{result.stderr.strip()}"
        return True, f"Updated {url}"
    else:
        result = _run(["git", "clone", "--depth", "1", url, str(dest)])
        if result.returncode != 0:
            return False, f"git clone failed for {url}:\n{result.stderr.strip()}"
        return True, f"Cloned {url}"


def current_commit(url: str) -> str | None:
    """Return the current HEAD commit hash for the cached repo, or None."""
    dest = cache_path(url)
    if not dest.exists():
        return None
    result = _run(["git", "rev-parse", "--short", "HEAD"], cwd=dest)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def is_cached(url: str) -> bool:
    return cache_path(url).exists()
