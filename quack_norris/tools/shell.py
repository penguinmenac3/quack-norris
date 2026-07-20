"""Shell execution tool.

Named ``pwsh`` on Windows and ``bash`` on Linux/Mac so the LLM knows
which shell syntax to use. Requires user approval before execution.

When a command is still running after its timeout it is NOT killed.
Instead it is registered in the session ``ProcessRegistry`` and the
LLM receives a handle it can use with ``check_tool``, ``await_tool``,
or ``kill_tool``.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from quack_norris.core.llm import Param, Tool, ToolResult, tool

if TYPE_CHECKING:
    from quack_norris.tools.background import ProcessRegistry


# Background-promotion threshold: commands still running after this many
# seconds are moved to the registry rather than killed (seconds).
_BACKGROUND_THRESHOLD = 30


async def _run_shell(
    command: str,
    cwd: str,
    default_cwd: Path,
    registry: "ProcessRegistry | None" = None,
) -> ToolResult:
    effective_cwd = cwd or str(default_cwd)
    effective_timeout = _BACKGROUND_THRESHOLD

    if sys.platform == "win32":
        shell_argv = ["pwsh", "-Command", command]
    else:
        shell_argv = ["bash", "-c", command]

    try:
        proc = await asyncio.create_subprocess_exec(
            *shell_argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=effective_cwd,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
        except asyncio.TimeoutError:
            # ── Background promotion ──────────────────────────────────────
            # Timeout is always 30 s; promote to background if a registry is
            # available, otherwise kill (no-registry path, e.g. tests).
            if registry is not None:
                rp = registry.register(proc, command)
                handle = rp.handle
                return ToolResult(
                    content=(
                        f"Process still running after {effective_timeout}s.  Handle: {handle}\n"
                        f"Use check_tool(handle='{handle}') to poll output so far, "
                        f"await_tool(handle='{handle}') to wait for completion and read the full output, "
                        f"or kill_tool(handle='{handle}') to terminate."
                    )
                )
            proc.kill()
            return ToolResult(content=f"Command timed out after {effective_timeout}s.", is_error=True)

        output = stdout.decode(errors="replace").strip()
        if proc.returncode != 0:
            return ToolResult(
                content=f"Exit code {proc.returncode}\n{output}" if output else f"Exit code {proc.returncode}",
                is_error=True,
            )
        return ToolResult(content=output or "(no output)")
    except FileNotFoundError as exc:
        return ToolResult(content=f"Shell not found: {exc}", is_error=True)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(content=str(exc), is_error=True)


def make_shell_tool(
    get_cwd: "Callable[[], Path]",
    registry: "ProcessRegistry | None" = None,
) -> "Tool":
    """Return the platform shell tool bound to get_cwd for CWD-aware approval.

    The needs_approval predicate always returns True (shell always needs approval),
    but also forces approval when the cwd argument resolves outside the project root,
    preventing whitelist patterns from silently approving out-of-project shell runs.

    Parameters
    ----------
    get_cwd:
        Callable that returns the current project root ``Path``.
    registry:
        Optional ``ProcessRegistry``.  When provided, commands that are still
        running after their timeout are promoted to background processes
        instead of being killed.
    """
    from quack_norris.tools.files import _resolve, _is_outside

    def _shell_needs_approval(args: dict):
        raw_cwd = args.get("cwd") or ""
        if raw_cwd:
            project_root = get_cwd()
            resolved = _resolve(raw_cwd, project_root)
            if _is_outside(resolved, project_root):
                return "human"  # outside CWD: skip whitelist, always ask human
        return True  # inside CWD: check whitelist first

    _cwd_note = (
        "Working directory for the command. Omit entirely to run in the project root. "
        "Use a relative path if needed (e.g. 'sub/dir'); absolute paths are only acceptable "
        "when running outside the project."
    )

    if sys.platform == "win32":
        @tool(needs_approval=_shell_needs_approval, show_output=True)
        async def pwsh(
            command: Annotated[str, Param("The PowerShell command to execute. Do NOT prefix with 'cd ...' — use the cwd parameter instead, or omit it entirely to run in the project root.")],
            cwd: Annotated[str, Param(_cwd_note)] = "",
        ) -> ToolResult:
            """Execute a PowerShell (pwsh) command and return its output (stdout + stderr combined)."""
            return await _run_shell(command, cwd, get_cwd(), registry)

        from quack_norris.tools.files import attach_path_normalizer
        attach_path_normalizer([pwsh], get_cwd)
        return pwsh

    else:
        @tool(needs_approval=_shell_needs_approval, show_output=True)
        async def bash(
            command: Annotated[str, Param("The bash command to execute. Do NOT prefix with 'cd ...' — use the cwd parameter instead, or omit it entirely to run in the project root.")],
            cwd: Annotated[str, Param(_cwd_note)] = "",
        ) -> ToolResult:
            """Execute a bash command and return its output (stdout + stderr combined)."""
            return await _run_shell(command, cwd, get_cwd(), registry)

        from quack_norris.tools.files import attach_path_normalizer
        attach_path_normalizer([bash], get_cwd)
        return bash
