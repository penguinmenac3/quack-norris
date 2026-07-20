"""Approval whitelist — load, match, and save auto-approval rules.

File format (version: 1):

    version: 1
    pwsh:
      - pattern: "git *"
      - pattern: "uv run *"
    file_write:
      - pattern: "src/**"
    file_view:
      - pattern: "**"

Load order (first match wins, checked in order):
  1. In-memory session rules (added via "allow pattern" during a session)
  2. Project whitelist  — <project-root>/.quack-whitelist.yaml
  3. Global whitelist   — ~/.quack-norris/whitelist.yaml

Pattern syntax:
  *   matches any characters except /
  **  matches any characters including /
  Matching is case-insensitive on Windows, case-sensitive elsewhere.
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
    _YAML_OK = True
except ImportError:
    _YAML_OK = False


# ---------------------------------------------------------------------------
# Which argument to match against for each tool
# ---------------------------------------------------------------------------

_TOOL_MATCH_ARG: dict[str, str] = {
    "pwsh":            "command",
    "bash":            "command",
    "file_view":       "path",
    "file_write":      "path",
    "file_str_replace": "path",
    "file_move":       "source",
    "file_delete":     "path",
    "switch_agent":    "name",
    "switch_project":  "path",
    "spawn_subagent":  "agent_name",
}


# ---------------------------------------------------------------------------
# Rule + Whitelist
# ---------------------------------------------------------------------------

class Whitelist:
    """Holds merged whitelist rules across session / project / global scopes."""

    def __init__(self) -> None:
        self._session: dict[str, list[str]] = {}   # tool → [pattern, ...]
        self._project: dict[str, list[str]] = {}
        self._global:  dict[str, list[str]] = {}
        self._project_path: Path | None = None
        self._global_path: Path = Path.home() / ".quack-norris" / "whitelist.yaml"

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, project_root: Path | None) -> None:
        """Load project and global whitelist files."""
        self._project_path = (project_root / ".quack-whitelist.yaml") if project_root else None
        self._project = _load_file(self._project_path)
        self._global  = _load_file(self._global_path)

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def is_whitelisted(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Return True if this tool call matches any loaded rule."""
        arg_name = _TOOL_MATCH_ARG.get(tool_name)
        value = str(arguments.get(arg_name, "")) if arg_name else ""

        for ruleset in (self._session, self._project, self._global):
            for pattern in ruleset.get(tool_name, []):
                if _match(pattern, value):
                    return True
        return False

    # ------------------------------------------------------------------
    # Adding rules
    # ------------------------------------------------------------------

    def add_session_rule(self, tool_name: str, pattern: str) -> None:
        self._session.setdefault(tool_name, []).append(pattern)

    def add_project_rule(self, tool_name: str, pattern: str) -> None:
        self._project.setdefault(tool_name, []).append(pattern)
        if self._project_path:
            _save_file(self._project_path, self._project)

    def add_global_rule(self, tool_name: str, pattern: str) -> None:
        self._global.setdefault(tool_name, []).append(pattern)
        _save_file(self._global_path, self._global)

    # ------------------------------------------------------------------
    # Pattern suggestions
    # ------------------------------------------------------------------

    def suggest_patterns(self, tool_name: str, arguments: dict[str, Any]) -> list[str]:
        """Return ordered pattern suggestions from most specific to most permissive."""
        arg_name = _TOOL_MATCH_ARG.get(tool_name)
        value = str(arguments.get(arg_name, "")) if arg_name else ""
        if not value:
            return ["*"]
        return _generate_suggestions(tool_name, value)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _match(pattern: str, value: str) -> bool:
    # Always normalise to forward slashes so patterns written as `src/**`
    # match Windows paths that arrive with backslashes.
    pattern = pattern.replace("\\", "/")
    value = value.replace("\\", "/")
    case_sensitive = sys.platform != "win32"
    if not case_sensitive:
        pattern = pattern.lower()
        value = value.lower()
    return fnmatch.fnmatchcase(value, pattern)


def _load_file(path: Path | None) -> dict[str, list[str]]:
    if not _YAML_OK or path is None or not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        result: dict[str, list[str]] = {}
        for tool_name, entries in data.items():
            if tool_name == "version":
                continue
            if isinstance(entries, list):
                patterns = [e["pattern"] for e in entries if isinstance(e, dict) and "pattern" in e]
                if patterns:
                    result[tool_name] = patterns
        return result
    except Exception:  # noqa: BLE001
        return {}


def _save_file(path: Path, rules: dict[str, list[str]]) -> None:
    if not _YAML_OK:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"version": 1}
        for tool_name, patterns in sorted(rules.items()):
            data[tool_name] = [{"pattern": p} for p in patterns]
        path.write_text(yaml.safe_dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _generate_suggestions(tool_name: str, value: str) -> list[str]:
    """Generate glob pattern suggestions from most specific to most permissive."""
    suggestions: list[str] = [value.replace("\\", "/")]  # exact match always first, normalised to forward slashes

    if tool_name in ("pwsh", "bash"):
        parts = value.split()
        if len(parts) >= 2:
            suggestions.append(f"{parts[0]} {parts[1]} *")
        if parts:
            suggestions.append(f"{parts[0]} *")

    elif tool_name in ("file_view", "file_write", "file_str_replace", "file_move", "file_delete"):
        p = Path(value)
        if p.suffix:
            suggestions.append(str(p.parent / f"*{p.suffix}").replace("\\", "/"))
        suggestions.append(str(p.parent / "*").replace("\\", "/"))
        parts = p.parts
        if len(parts) > 1:
            suggestions.append(str(Path(parts[0]) / "**").replace("\\", "/"))
        suggestions.append("**")

    elif tool_name in ("switch_agent", "switch_project", "spawn_subagent"):
        suggestions.append("*")

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result
