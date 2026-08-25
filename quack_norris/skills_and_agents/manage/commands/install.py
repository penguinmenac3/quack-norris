"""install command — copy a skill or agent from a source repo to a target location."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ..cache import current_commit
from ..discovery import find_item_in_repo, scan_all
from ..manifest import InstalledItem, add_item, find_item, load_manifest, now_iso
from ..paths import (
    find_project_root,
    global_agents_dir,
    resolve_install_root,
    skill_install_dir,
    tool_agent_dirs,
)
from ..sources import SourceEntry, all_source_entries, all_sources
from .update import sync_sources

_TOOL_FLAGS = ["quack-norris", "copilot", "claude", "windsurf", "continue"]


def _is_local_path(target: str) -> bool:
    """Return True if *target* looks like a filesystem path rather than a registry target."""
    t = target.split("=")[0]  # strip alias before checking
    if t.startswith(("./", "../", "/", "~")):
        return True
    # Windows absolute paths (C:\...) or backslash separators
    if len(t) >= 2 and t[1] == ":":
        return True
    if "\\" in t:
        return True
    return False


def _infer_type_from_path(local_path: Path) -> str | None:
    """Detect whether *local_path* is a skill or agent by inspecting its contents."""
    if local_path.is_dir():
        if (local_path / "SKILL.md").exists():
            return "skill"
        agent_files = list(local_path.glob("*.agent.md"))
        skill_files = list(local_path.glob("*.skill.md"))
        if skill_files and not agent_files:
            return "skill"
        if agent_files and not skill_files:
            return "agent"
        return None
    if local_path.suffix == ".md":
        if local_path.stem.endswith(".skill") or local_path.name == "SKILL.md":
            return "skill"
        if local_path.stem.endswith(".agent") or local_path.name.endswith(".agent.md"):
            return "agent"
    return None


def _parse_target(target: str) -> tuple[str | None, str, str | None]:
    """Parse a target string.

    Accepts:
      - 'name[=alias]'                — registry target, type auto-detected
      - 'name.skill[=alias]'          — registry target, explicit skill
      - 'name.agent[=alias]'          — registry target, explicit agent
      - './path[=alias]' or any path  — local install, type inferred from files

    Returns (item_type_or_None, source_path_or_raw, local_name_override).
    item_type is None when auto-detection is needed.
    """
    local_name_override: str | None = None
    if "=" in target:
        raw, local_name_override = target.rsplit("=", 1)
    else:
        raw = target

    if _is_local_path(raw):
        return None, raw, local_name_override

    # Explicit type via .skill / .agent suffix (e.g. "concise-writer.skill")
    if raw.endswith(".skill"):
        return "skill", raw[: -len(".skill")], local_name_override
    if raw.endswith(".agent"):
        return "agent", raw[: -len(".agent")], local_name_override

    return None, raw, local_name_override


def _resolve_active_tools(args: argparse.Namespace) -> list[str]:
    """Return the list of tool names to install for. Defaults to ['quack-norris']."""
    requested = [t for t in _TOOL_FLAGS if getattr(args, t.replace("-", "_"), False)]
    return requested if requested else ["quack-norris"]


def _resolve_src_file_from_local(local_path: Path) -> Path | None:
    """Return the canonical source file for a local skill/agent path.

    For directories: returns SKILL.md, *.skill.md, or *.agent.md inside it.
    For files: returns the file itself if recognised.
    """
    if local_path.is_dir():
        skill_md = local_path / "SKILL.md"
        if skill_md.exists():
            return skill_md
        for f in local_path.glob("*.skill.md"):
            return f
        for f in local_path.glob("*.agent.md"):
            return f
        return None
    if local_path.exists() and local_path.suffix == ".md":
        return local_path
    return None


def _install_local(
    raw_target: str,
    install_root: Path,
    active_tools: list[str],
    local_name_override: str | None,
) -> bool:
    """Install directly from a local filesystem path. Returns True on success."""
    local_path = Path(raw_target).expanduser().resolve()

    if not local_path.exists():
        print(f"error: path does not exist: {local_path}", file=sys.stderr)
        return False

    item_type = _infer_type_from_path(local_path)
    if item_type is None:
        print(
            f"error: cannot determine whether '{local_path}' is a skill or agent. "
            "Expected a directory with SKILL.md / *.skill.md / *.agent.md, or a matching .md file.",
            file=sys.stderr,
        )
        return False

    src_file = _resolve_src_file_from_local(local_path)
    if src_file is None:
        print(f"error: no skill/agent file found in '{local_path}'.", file=sys.stderr)
        return False

    local_name = local_name_override if local_name_override else local_path.name
    source_path = str(local_path)

    existing = load_manifest(install_root)
    conflict = find_item(existing, item_type=item_type, local_name=local_name)
    if conflict:
        print(
            f"error: {item_type} '{local_name}' already installed — use =<alias> to install under a different name.",
            file=sys.stderr,
        )
        return False

    if item_type == "skill":
        skills_dir = skill_install_dir(install_root)
        dest_skill_dir = skills_dir / local_name
        if dest_skill_dir.exists():
            print(
                f"error: skill directory already exists at {dest_skill_dir}. "
                "Install under a different name with =<new-name>.",
                file=sys.stderr,
            )
            return False
        if local_path.is_dir():
            shutil.copytree(local_path, dest_skill_dir)
        else:
            dest_skill_dir.mkdir(parents=True)
            shutil.copy2(src_file, dest_skill_dir / "SKILL.md")
        print(f"Installed skill '{local_name}' → {dest_skill_dir}/")

        add_item(
            install_root,
            InstalledItem(
                type="skill",
                local_name=local_name,
                source_url="local",
                source_path=source_path,
                commit="local",
                installed_at=now_iso(),
            ),
        )

    else:  # agent
        tool_dirs = tool_agent_dirs(install_root, active_tools)

        for tool_name, dest_dir in tool_dirs.items():
            dest_file = dest_dir / f"{local_name}.agent.md"
            if dest_file.exists():
                print(
                    f"error: agent file already exists at {dest_file} (for tool '{tool_name}'). "
                    "Install under a different name with =<new-name>.",
                    file=sys.stderr,
                )
                return False
            shutil.copy2(src_file, dest_file)
            print(f"Installed agent '{local_name}' [{tool_name}] → {dest_file}")

        add_item(
            install_root,
            InstalledItem(
                type="agent",
                local_name=local_name,
                source_url="local",
                source_path=source_path,
                commit="local",
                installed_at=now_iso(),
                tools=active_tools,
            ),
        )

    return True


def _install_one(
    raw_target: str,
    install_root: Path,
    all_items: list,
    active_tools: list[str],
    explicit_source: str | None,
) -> bool:
    """Install a single target. Returns True on success, False on error."""
    item_type, source_path, local_name_override = _parse_target(raw_target)

    if item_type is None and _is_local_path(raw_target.split("=")[0]):
        return _install_local(raw_target.split("=")[0], install_root, active_tools, local_name_override)

    local_name = local_name_override if local_name_override else source_path.split("/")[-1]

    if item_type is not None:
        matches = [
            i for i in all_items
            if i.type == item_type
            and (i.source_path == source_path or i.source_path.endswith("/" + source_path))
        ]
    else:
        matches = [
            i for i in all_items
            if i.source_path == source_path or i.source_path.endswith("/" + source_path)
        ]

    if not matches:
        qualifier = f"{item_type}/{source_path}" if item_type else source_path
        print(
            f"error: '{qualifier}' not found in any registered source.",
            file=sys.stderr,
        )
        return False

    if len(matches) > 1:
        types_involved = {i.type for i in matches}
        if len(types_involved) > 1:
            short_name = source_path.split("/")[-1]
            suggestions = "\n".join(
                f"  quack-norris-manage install {short_name}.{i.type}" for i in matches
            )
            print(
                f"error: '{source_path}' matches both skills and agents. Disambiguate with a suffix:\n{suggestions}",
                file=sys.stderr,
            )
            return False
        options = "\n".join(f"  {i.source_path}  ({i.source_url})" for i in matches)
        paths_identical = len({i.source_path for i in matches}) == 1
        if paths_identical:
            suggestions = "\n".join(
                f"  quack-norris-manage install {matches[0].source_path} --source {i.source_url}"
                for i in matches
            )
            hint = f"All matches have the same path. Use --source to pick the repo:\n{suggestions}"
        else:
            suggestions = "\n".join(
                f"  quack-norris-manage install {i.source_path}" for i in matches
            )
            hint = f"Be more specific, e.g.:\n{suggestions}"
        print(
            f"error: '{source_path}' is ambiguous — multiple matches found:\n{options}\n{hint}",
            file=sys.stderr,
        )
        return False

    resolved_type = matches[0].type

    existing = load_manifest(install_root)
    conflict = find_item(existing, item_type=resolved_type, local_name=local_name)
    if conflict:
        print(
            f"error: {resolved_type} '{local_name}' already installed from '{conflict.source_path}' — use =<alias> to install under a different name.",
            file=sys.stderr,
        )
        return False

    source_url = matches[0].source_url
    src_file = find_item_in_repo(source_url, matches[0].source_path)
    source_path = matches[0].source_path  # use the full resolved path

    if src_file is None:
        print(
            f"error: '{resolved_type}/{source_path}' was discovered but the file could not be located. "
            f"Try running `quack-norris-manage update`.",
            file=sys.stderr,
        )
        return False

    commit = current_commit(source_url) or "unknown"

    if resolved_type == "skill":
        skills_dir = skill_install_dir(install_root)
        dest_skill_dir = skills_dir / local_name
        if dest_skill_dir.exists():
            print(
                f"error: skill directory already exists at {dest_skill_dir}. "
                f"Install under a different name with =<new-name>.",
                file=sys.stderr,
            )
            return False
        if src_file.name == "SKILL.md":
            shutil.copytree(src_file.parent, dest_skill_dir)
        else:
            dest_skill_dir.mkdir(parents=True)
            shutil.copy2(src_file, dest_skill_dir / "SKILL.md")
        print(f"Installed skill '{local_name}' → {dest_skill_dir}/")

        add_item(
            install_root,
            InstalledItem(
                type="skill",
                local_name=local_name,
                source_url=source_url,
                source_path=source_path,
                commit=commit,
                installed_at=now_iso(),
            ),
        )

    else:  # agent
        tool_dirs = tool_agent_dirs(install_root, active_tools)

        for tool_name, dest_dir in tool_dirs.items():
            dest_file = dest_dir / f"{local_name}.agent.md"
            if dest_file.exists():
                print(
                    f"error: agent file already exists at {dest_file} (for tool '{tool_name}'). "
                    f"Install under a different name with =<new-name>.",
                    file=sys.stderr,
                )
                return False
            shutil.copy2(src_file, dest_file)
            print(f"Installed agent '{local_name}' [{tool_name}] → {dest_file}")

        add_item(
            install_root,
            InstalledItem(
                type="agent",
                local_name=local_name,
                source_url=source_url,
                source_path=source_path,
                commit=commit,
                installed_at=now_iso(),
                tools=active_tools,
            ),
        )

    return True


def cmd_install(args: argparse.Namespace) -> None:
    use_global: bool = args.global_
    use_local: bool = getattr(args, "local", False)
    explicit_source: str | None = args.source

    install_root = resolve_install_root(use_global=use_global, use_local=use_local)
    active_tools = _resolve_active_tools(args)

    project_root = find_project_root()
    source_urls = [explicit_source] if explicit_source else all_sources(global_agents_dir(), project_root)

    all_targets_local = all(_is_local_path(t.split("=")[0]) for t in args.target)

    if not source_urls and not all_targets_local:
        print("error: no sources registered. Use `quack-norris-manage source add <url>`.", file=sys.stderr)
        sys.exit(1)

    if all_targets_local:
        pass  # no source sync needed for local installs
    elif not explicit_source:
        sync_sources()
    else:
        from ..cache import fetch, is_cached
        if not is_cached(explicit_source):
            print(f"Fetching {explicit_source}...")
            ok, msg = fetch(explicit_source)
            if not ok:
                print(f"  ✗ {msg}", file=sys.stderr)

    if explicit_source:
        source_entries = [SourceEntry(url=explicit_source)]
    else:
        source_entries = all_source_entries(global_agents_dir(), project_root)
    all_items = scan_all(source_entries) if source_entries else []

    targets: list[str] = args.target
    errors = 0
    for raw_target in targets:
        ok = _install_one(raw_target, install_root, all_items, active_tools, explicit_source)
        if not ok:
            errors += 1

    if errors:
        sys.exit(1)
