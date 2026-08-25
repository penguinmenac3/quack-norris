from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from acp.schema import PermissionOption


@dataclass(frozen=True)
class ApprovalRule:
    tool: str
    pattern: str


@dataclass(frozen=True)
class ApprovalChoice:
    option: PermissionOption
    scope: str | None = None
    rule: ApprovalRule | None = None


class ApprovalPolicy:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        home = Path(
            os.environ.get(
                "QUACK_NORRIS_HOME",
                Path.home() / ".config" / "quack-norris",
            )
        )
        self.project_path = self.project_root / ".quack-whitelist.yaml"
        self.global_path = home / "whitelist.yaml"

    def is_allowed(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        value = _approval_value(tool_name, arguments)
        for path in (self.project_path, self.global_path):
            for rule in _load_rules(path):
                if rule.tool == tool_name and _matches(value, rule.pattern):
                    return True
        return False

    def choices(self, tool_name: str, arguments: dict[str, Any]) -> list[ApprovalChoice]:
        value = _approval_value(tool_name, arguments)
        exact = ApprovalRule(tool_name, value)
        choices = [
            ApprovalChoice(
                PermissionOption(option_id="allow_once", name="Allow once", kind="allow_once")
            ),
            ApprovalChoice(
                PermissionOption(
                    option_id="allow_project_exact",
                    name=f"Always allow in this project: {value}",
                    kind="allow_always",
                ),
                scope="project",
                rule=exact,
            ),
            ApprovalChoice(
                PermissionOption(
                    option_id="allow_global_exact",
                    name=f"Always allow globally: {value}",
                    kind="allow_always",
                ),
                scope="global",
                rule=exact,
            ),
        ]
        command_pattern = _command_pattern(tool_name, value)
        if command_pattern and command_pattern != value:
            family = ApprovalRule(tool_name, command_pattern)
            choices.extend(
                [
                    ApprovalChoice(
                        PermissionOption(
                            option_id="allow_project_command",
                            name=f"Always allow in this project: {command_pattern}",
                            kind="allow_always",
                        ),
                        scope="project",
                        rule=family,
                    ),
                    ApprovalChoice(
                        PermissionOption(
                            option_id="allow_global_command",
                            name=f"Always allow globally: {command_pattern}",
                            kind="allow_always",
                        ),
                        scope="global",
                        rule=family,
                    ),
                ]
            )
        choices.append(
            ApprovalChoice(
                PermissionOption(option_id="reject_once", name="Reject", kind="reject_once")
            )
        )
        return choices

    def persist(self, choice: ApprovalChoice) -> None:
        if choice.rule is None or choice.scope is None:
            return
        path = self.project_path if choice.scope == "project" else self.global_path
        rules = _load_rules(path)
        if choice.rule not in rules:
            rules.append(choice.rule)
            _save_rules(path, rules)


def _approval_value(tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name in {"pwsh", "bash"}:
        return " ".join(str(arguments.get("command", "")).split())
    source, destination = arguments.get("source"), arguments.get("destination")
    if isinstance(source, str) and isinstance(destination, str):
        normalized_source = source.replace("\\", "/")
        normalized_destination = destination.replace("\\", "/")
        return f"{normalized_source} -> {normalized_destination}"
    for key in ("path", "source", "destination"):
        value = arguments.get(key)
        if isinstance(value, str) and value:
            return value.replace("\\", "/")
    return json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _command_pattern(tool_name: str, value: str) -> str | None:
    if tool_name not in {"pwsh", "bash"}:
        return None
    match = re.match(r"\s*([^\s|;&]+)", value)
    return f"{match.group(1)} *" if match else None


def _matches(value: str, pattern: str) -> bool:
    if os.name == "nt":
        value, pattern = value.casefold(), pattern.casefold()
    return fnmatch.fnmatchcase(value, pattern)


def _load_rules(path: Path) -> list[ApprovalRule]:
    if not path.exists():
        return []
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    entries = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    rules: list[ApprovalRule] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tool_name, pattern = entry.get("tool"), entry.get("pattern")
        if isinstance(tool_name, str) and isinstance(pattern, str):
            rules.append(ApprovalRule(tool_name, pattern))
    return rules


def _save_rules(path: Path, rules: list[ApprovalRule]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "rules": [
            {"tool": rule.tool, "pattern": rule.pattern}
            for rule in sorted(rules, key=lambda item: (item.tool, item.pattern))
        ],
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    temporary.replace(path)
