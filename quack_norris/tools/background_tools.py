"""Auto-approved tools for interacting with background processes.

These three tools let the LLM poll, wait for, or terminate a process that
was promoted to a background handle by ``shell.py`` after exceeding the
30-second timeout.

All three are ``needs_approval=False`` because the original shell command
was already approved by the user — there is nothing new to authorise.
"""

from __future__ import annotations

import contextlib
from typing import Annotated

from quack_norris.core.llm import Param, Tool, ToolResult, tool
from quack_norris.tools.background import ProcessRegistry

# Sentinel content prefix used by the renderer to detect background handles.
_BG_RUNNING_PREFIX = "⏳ still running"


def make_operation_tools(registry: ProcessRegistry) -> list[Tool]:
    """Return [check_tool, await_tool, kill_tool] bound to *registry*."""

    # ------------------------------------------------------------------ #
    # check_tool                                                           #
    # ------------------------------------------------------------------ #

    @tool(needs_approval=False, show_output=True)
    async def check_tool(
        handle: Annotated[str, Param("Background process handle, e.g. 'bg-3f2a'")],
    ) -> ToolResult:
        """Return buffered stdout so far and whether the process is still running."""
        rp = registry.get(handle)
        if rp is None:
            return ToolResult(
                content=f"No background process with handle '{handle}'. "
                        f"Known handles: {registry.all_handles() or '(none)'}",
                is_error=True,
            )

        output = rp.buffered_output()
        if rp.finished:
            ec = rp.exit_code if rp.exit_code is not None else "?"
            status = f"Process finished (exit code {ec})."
        else:
            elapsed = int(rp.uptime_seconds())
            status = f"{_BG_RUNNING_PREFIX} — handle: {handle}  (running {elapsed}s)"

        body = f"{status}\n{output}" if output else status
        return ToolResult(content=body)

    # ------------------------------------------------------------------ #
    # await_tool                                                           #
    # ------------------------------------------------------------------ #

    @tool(needs_approval=False, show_output=True)
    async def await_tool(
        handle: Annotated[str, Param("Background process handle, e.g. 'bg-3f2a'")],
    ) -> ToolResult:
        """Block until the background process finishes and return its full output."""
        rp = registry.get(handle)
        if rp is None:
            return ToolResult(
                content=f"No background process with handle '{handle}'. "
                        f"Known handles: {registry.all_handles() or '(none)'}",
                is_error=True,
            )

        # If already finished, just return what we have.
        if not rp.finished and rp._drain_task is not None:
            await rp._drain_task  # wait for drain task to complete

        output = rp.buffered_output()
        ec = rp.exit_code if rp.exit_code is not None else "?"
        header = f"Process finished (exit code {ec})."
        body = f"{header}\n{output}" if output else header

        if isinstance(ec, int) and ec != 0:
            return ToolResult(content=body, is_error=True)
        return ToolResult(content=body)

    # ------------------------------------------------------------------ #
    # kill_tool                                                            #
    # ------------------------------------------------------------------ #

    @tool(needs_approval=False, show_output=True)
    async def kill_tool(
        handle: Annotated[str, Param("Background process handle, e.g. 'bg-3f2a'")],
    ) -> ToolResult:
        """Terminate the background process and return captured output so far."""
        rp = registry.get(handle)
        if rp is None:
            return ToolResult(
                content=f"No background process with handle '{handle}'. "
                        f"Known handles: {registry.all_handles() or '(none)'}",
                is_error=True,
            )

        if rp.finished:
            ec = rp.exit_code if rp.exit_code is not None else "?"
            return ToolResult(
                content=f"Process {handle} already finished (exit code {ec})."
            )

        with contextlib.suppress(ProcessLookupError):  # already gone
            rp.proc.kill()

        # Wait for drain task to flush remaining output before returning.
        if rp._drain_task is not None:
            try:
                import asyncio
                await asyncio.wait_for(rp._drain_task, timeout=5.0)
            except TimeoutError:
                pass

        output = rp.buffered_output()
        ec = rp.exit_code if rp.exit_code is not None else "?"
        header = f"Process {handle} killed (exit code {ec})."
        body = f"{header}\n{output}" if output else header
        return ToolResult(content=body)

    return [check_tool, await_tool, kill_tool]


make_background_tools = make_operation_tools
