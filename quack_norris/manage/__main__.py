"""quack-norris-manage CLI entry point."""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _add_scope_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--global",
        dest="global_",
        action="store_true",
        default=False,
        help="Operate on the global install location (~/.agents/).",
    )
    group.add_argument(
        "--local",
        action="store_true",
        default=False,
        help="Operate on the current working directory (CWD/.agents/).",
    )


def _add_tool_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--quack-norris", action="store_true", default=False)
    parser.add_argument("--copilot", action="store_true", default=False)
    parser.add_argument("--claude", action="store_true", default=False)
    parser.add_argument("--windsurf", action="store_true", default=False)
    parser.add_argument("--continue", dest="continue_", action="store_true", default=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quack-norris-manage",
        description="Manage quack-norris agents and skills.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── source ────────────────────────────────────────────────────────────
    source_p = sub.add_parser("source", help="Manage source repositories.")
    source_sub = source_p.add_subparsers(dest="source_command", required=True)

    src_add = source_sub.add_parser("add", help="Register a git source URL.")
    src_add.add_argument("url", nargs="+", help="One or more git repository URLs.")
    src_add_scope = src_add.add_mutually_exclusive_group()
    src_add_scope.add_argument(
        "--global",
        dest="scope",
        action="store_const",
        const="global",
        default="project",
        help="Add to global sources (~/.agents/sources.yaml).",
    )

    src_remove = source_sub.add_parser("remove", help="Remove a registered source URL.")
    src_remove.add_argument("url", nargs="+", help="One or more git repository URLs.")
    src_remove_scope = src_remove.add_mutually_exclusive_group()
    src_remove_scope.add_argument(
        "--global",
        dest="scope",
        action="store_const",
        const="global",
        default="project",
        help="Remove from global sources.",
    )

    source_sub.add_parser("list", help="List all registered source URLs.")

    # ── list ──────────────────────────────────────────────────────────────
    list_p = sub.add_parser("list", help="List available skills and agents.")
    list_p.add_argument(
        "--details",
        action="store_true",
        default=False,
        help="Show description from frontmatter.",
    )
    list_p.add_argument(
        "--installed",
        action="store_true",
        default=False,
        help="Show only installed items (no source scan).",
    )
    _add_scope_flags(list_p)

    # ── install ───────────────────────────────────────────────────────────
    install_p = sub.add_parser(
        "install",
        help="Install a skill or agent from a registered source or a local path.",
    )
    install_p.add_argument(
        "target",
        nargs="+",
        help=(
            "One or more targets to install. Examples: "
            "'concise-writer', 'concise-writer.skill', 'planner.agent=my-planner', "
            "'./my-local-skill', '../some-agent.agent.md'."
        ),
    )
    install_p.add_argument(
        "--source",
        metavar="URL",
        default=None,
        help="Use a specific git URL instead of registered sources.",
    )
    _add_scope_flags(install_p)
    _add_tool_flags(install_p)

    # ── uninstall ─────────────────────────────────────────────────────────
    uninstall_p = sub.add_parser("uninstall", help="Remove an installed skill or agent.")
    uninstall_p.add_argument(
        "target",
        nargs="+",
        help="One or more targets to remove, e.g. 'concise-writer' or 'concise-writer.skill' if ambiguous.",
    )
    _add_scope_flags(uninstall_p)

    # ── upgrade ───────────────────────────────────────────────────────────
    upgrade_p = sub.add_parser("upgrade", help="Upgrade installed skills/agents to latest.")
    upgrade_p.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Optional: name of item to upgrade (e.g. 'concise-writer', or 'concise-writer.skill' if ambiguous). Upgrades all if omitted.",
    )
    upgrade_p.add_argument(
        "-y", "--yes",
        action="store_true",
        default=False,
        help="Skip confirmation prompt and upgrade immediately.",
    )
    _add_scope_flags(upgrade_p)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "source":
        from .commands.source import cmd_source_add, cmd_source_list, cmd_source_remove

        if args.source_command == "add":
            cmd_source_add(args)
        elif args.source_command == "remove":
            cmd_source_remove(args)
        elif args.source_command == "list":
            cmd_source_list(args)

    elif args.command == "list":
        from .commands.list import cmd_list

        cmd_list(args)

    elif args.command == "install":
        from .commands.install import cmd_install

        cmd_install(args)

    elif args.command == "uninstall":
        from .commands.uninstall import cmd_uninstall

        cmd_uninstall(args)

    elif args.command == "upgrade":
        from .commands.upgrade import cmd_upgrade

        cmd_upgrade(args)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
