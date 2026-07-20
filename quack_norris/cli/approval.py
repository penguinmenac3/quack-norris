"""Interactive approval handler.

Implements on_permission_request for the agent loop.

Prompt UX:
  Allow once (Y), allow pattern (p) or deny (d/n)? (Y/p/d) >
  Y / Enter  — allow once
  p          — show pattern picker, save rule, then allow
  d / n      — deny, then optionally provide a reason for the LLM
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

from quack_norris.cli.input import read_single_line
from quack_norris.cli.renderer import _format_args_multiline
from quack_norris.core.agent import ToolCallOutput
from quack_norris.core.llm import ToolResult

if TYPE_CHECKING:
    from quack_norris.cli.whitelist import Whitelist

# Sentinel used by _run_turn to detect a denial with an optional reason.
# interactive_approval returns this instead of False when denied interactively.
_DENIED_SENTINEL = object()


async def interactive_approval(
    call: ToolCallOutput,
    whitelist: "Whitelist | None" = None,
) -> bool | "ToolResult":
    """Ask the user to approve or deny a tool call.

    Returns:
        True            — approved (run the tool)
        ToolResult      — denied; .content carries the denial message incl. any
                          user-supplied reason, so the LLM sees it as a tool result
    If whitelist is provided and the call matches a rule, auto-approves silently.
    Runs blocking input() in a thread executor so it doesn't block the event loop.
    """
    if whitelist is not None and whitelist.is_whitelisted(call.tool_name, call.arguments or {}):
        args = _format_args_multiline(call.arguments or {}, truncate=True)
        if args:
            print(f"\n  ⚡ {call.tool_name}\n{args}", file=sys.stdout, flush=True)
        else:
            print(f"\n  ⚡ {call.tool_name}", file=sys.stdout, flush=True)
        return True

    # Needs real approval — print full multi-line block, no truncation.
    badge = "❗" if call.needs_approval == "human" else "⚠️"
    args = _format_args_multiline(call.arguments or {}, truncate=False)
    if args:
        print(f"\n  {badge} {call.tool_name}\n{args}", file=sys.stdout, flush=True)
    else:
        print(f"\n  {badge} {call.tool_name}", file=sys.stdout, flush=True)

    loop = asyncio.get_running_loop()
    while True:
        try:
            answer = await loop.run_in_executor(
                None,
                lambda: read_single_line("  Allow once (Y), allow pattern (p) or deny (d/n)? (Y/p/d) > "),
            )
        except (EOFError, KeyboardInterrupt):
            print("\n  ❌ denied", file=sys.stdout)
            return _make_denial(None)

        answer = answer.strip().lower()

        if answer in ("y", "yes", ""):
            print("  ✅ approved", file=sys.stdout)
            return True

        if answer == "p" and whitelist is not None:
            return await _pattern_picker(call, whitelist, loop)

        if answer == "p" and whitelist is None:
            print("  ✅ approved", file=sys.stdout)
            return True

        if answer in ("d", "n", "no", "deny"):
            reason = await _ask_reason(loop)
            return _make_denial(reason)

        print("  Please enter Y (allow once), p (allow pattern), or d/n (deny).", file=sys.stdout)


def _make_denial(reason: str | None) -> "ToolResult":
    """Build a denial ToolResult, optionally embedding the user's reason."""
    if reason:
        msg = f"Tool call was denied by the user. Reason: {reason}"
        print(f"  ❌ denied — {reason}", file=sys.stdout)
    else:
        msg = "Tool call was denied by the user."
        print("  ❌ denied", file=sys.stdout)
    return ToolResult(content=msg, is_error=True)


async def _ask_reason(loop: asyncio.AbstractEventLoop) -> str:
    """Prompt the user for an optional denial reason (Enter = no reason)."""
    try:
        reason = await loop.run_in_executor(
            None,
            lambda: read_single_line("  Reason (optional, Enter to skip) > "),
        )
        return reason.strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def auto_deny(call: ToolCallOutput) -> bool:
    """Always deny — used in non-interactive mode."""
    args = _format_args_multiline(call.arguments or {}, truncate=True)
    if args:
        print(f"  ❌ auto-denied: {call.tool_name}\n{args}", file=sys.stderr, flush=True)
    else:
        print(f"  ❌ auto-denied: {call.tool_name}", file=sys.stderr, flush=True)
    return False


async def auto_deny_async(call: ToolCallOutput) -> bool:
    return auto_deny(call)


# ---------------------------------------------------------------------------
# Pattern picker
# ---------------------------------------------------------------------------

async def _pattern_picker(call: ToolCallOutput, whitelist: Whitelist, loop: asyncio.AbstractEventLoop) -> bool:
    """Show pattern suggestions, let user pick scope, save rule, then approve."""
    suggestions = whitelist.suggest_patterns(call.tool_name, call.arguments or {})

    print("  Select a pattern to whitelist:", file=sys.stdout)
    for i, s in enumerate(suggestions):
        print(f"    [{i + 1}] {s}", file=sys.stdout)
    print(f"    [c] Custom pattern", file=sys.stdout)

    pattern: str | None = None
    while pattern is None:
        try:
            choice = await loop.run_in_executor(None, lambda: read_single_line("  Pattern (1/2/.../c) > "))
        except (EOFError, KeyboardInterrupt):
            print("\n  ❌ denied", file=sys.stdout)
            return False
        choice = choice.strip()
        if choice.lower() == "c":
            try:
                custom = await loop.run_in_executor(None, lambda: read_single_line("  Custom pattern > "))
            except (EOFError, KeyboardInterrupt):
                print("\n  ❌ denied", file=sys.stdout)
                return False
            pattern = custom.strip() or None
        elif choice.isdigit() and 1 <= int(choice) <= len(suggestions):
            pattern = suggestions[int(choice) - 1]
        else:
            print(f"  Enter a number between 1 and {len(suggestions)}, or c for custom.", file=sys.stdout)

    print("  Scope:", file=sys.stdout)
    print("    [s] This session only", file=sys.stdout)
    print("    [p] This project  (.quack-whitelist.yaml)", file=sys.stdout)
    print("    [g] Global        (~/.quack-norris/whitelist.yaml)", file=sys.stdout)

    scope: str | None = None
    while scope is None:
        try:
            s = await loop.run_in_executor(None, lambda: read_single_line("  Scope (s/p/g) > "))
        except (EOFError, KeyboardInterrupt):
            print("\n  ❌ denied", file=sys.stdout)
            return False
        s = s.strip().lower()
        if s in ("s", "session"):
            whitelist.add_session_rule(call.tool_name, pattern)
            scope = "session"
        elif s in ("p", "project"):
            whitelist.add_project_rule(call.tool_name, pattern)
            scope = "project"
        elif s in ("g", "global"):
            whitelist.add_global_rule(call.tool_name, pattern)
            scope = "global"
        else:
            print("  Enter s (session), p (project), or g (global).", file=sys.stdout)

    print(f"  ✅ approved + ⚡ whitelisted: '{pattern}' @ {scope}", file=sys.stdout)
    return True


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _format_args_only(call: ToolCallOutput) -> str:
    """Format tool arguments as key=value pairs, no tool-name wrapper."""
    if hasattr(call, "approval_display") and call.approval_display is not None:
        return call.approval_display()
    if not call.arguments:
        return "(no args)"
    parts = []
    for k, v in call.arguments.items():
        v_str = str(v)
        if len(v_str) > 80:
            v_str = v_str[:77] + "..."
        parts.append(f"{k}={v_str!r}")
    return ", ".join(parts)


def _format_call(call: ToolCallOutput) -> str:
    """Legacy wrapper — kept for any callers outside this module."""
    return f"{call.tool_name}({_format_args_only(call)})"
