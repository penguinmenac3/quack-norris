from __future__ import annotations

import asyncio
import contextlib
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from acp import Client
from acp.schema import EnvVariable

from quack_norris.core.llm import Param, Tool, ToolResult, tool


@dataclass
class TerminalOperation:
    operation_id: str
    terminal_id: str
    command: str
    wait_task: asyncio.Task[Any]


class ACPOperationRegistry:
    def __init__(self) -> None:
        self._operations: dict[str, TerminalOperation] = {}

    def add(
        self,
        terminal_id: str,
        command: str,
        wait_task: asyncio.Task[Any],
    ) -> TerminalOperation:
        operation = TerminalOperation(
            f"op-{uuid.uuid4().hex[:8]}", terminal_id, command, wait_task
        )
        self._operations[operation.operation_id] = operation
        return operation

    def get(self, operation_id: str) -> TerminalOperation | None:
        return self._operations.get(operation_id)

    def release(self, operation_id: str) -> None:
        self._operations.pop(operation_id, None)

    def ids(self) -> list[str]:
        return list(self._operations)

    def take_all(self) -> list[TerminalOperation]:
        operations = list(self._operations.values())
        self._operations.clear()
        return operations


def make_acp_tools(
    *,
    connection: Client,
    session_id: str,
    cwd: Path,
    additional_directories: tuple[Path, ...],
    can_read: bool,
    can_write: bool,
    can_use_terminal: bool,
    registry: ACPOperationRegistry,
    defer_threshold_seconds: float = 30.0,
) -> list[Tool]:
    tools: list[Tool] = []
    roots = (cwd.resolve(), *(path.resolve() for path in additional_directories))

    def resolve_path(raw_path: str) -> Path:
        path = Path(raw_path)
        resolved = (cwd / path).resolve() if not path.is_absolute() else path.resolve()
        if not any(resolved == root or root in resolved.parents for root in roots):
            raise ValueError(f"Path is outside the workspace: {raw_path}")
        return resolved

    if can_read:
        @tool(needs_approval=False)
        async def file_view(
            path: Annotated[str, Param("File path, relative to the workspace")],
            line: Annotated[int, Param("Optional 1-based starting line")] = 1,
            limit: Annotated[int, Param("Maximum number of lines")] = 200,
        ) -> ToolResult:
            try:
                response = await connection.read_text_file(
                    session_id,
                    str(resolve_path(path)),
                    line=max(1, line),
                    limit=max(1, min(limit, 2000)),
                )
                return ToolResult(content=response.content)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(content=str(exc), is_error=True)

        tools.append(file_view)

    if can_write:
        @tool(needs_approval=True)
        async def file_write(
            path: Annotated[str, Param("File path, relative to the workspace")],
            content: Annotated[str, Param("Complete text content to write")],
        ) -> ToolResult:
            try:
                resolved = resolve_path(path)
                await connection.write_text_file(session_id, str(resolved), content)
                return ToolResult(content=f"Wrote {path}")
            except Exception as exc:  # noqa: BLE001
                return ToolResult(content=str(exc), is_error=True)

        tools.append(file_write)

    if can_read and can_write:
        @tool(needs_approval=True)
        async def file_str_replace(
            path: Annotated[str, Param("File path, relative to the workspace")],
            old_string: Annotated[str, Param("Exact text to replace; must occur once")],
            new_string: Annotated[str, Param("Replacement text")],
        ) -> ToolResult:
            try:
                resolved = resolve_path(path)
                original = (await connection.read_text_file(session_id, str(resolved))).content
                count = original.count(old_string)
                if count != 1:
                    return ToolResult(
                        content=f"Expected old_string exactly once, found {count} occurrences.",
                        is_error=True,
                    )
                replacement = original.replace(old_string, new_string, 1)
                current = (await connection.read_text_file(session_id, str(resolved))).content
                if current != original:
                    return ToolResult(
                        content="File changed during edit; retry with fresh content.",
                        is_error=True,
                    )
                await connection.write_text_file(session_id, str(resolved), replacement)
                return ToolResult(content=f"Updated {path}")
            except Exception as exc:  # noqa: BLE001
                return ToolResult(content=str(exc), is_error=True)

        tools.append(file_str_replace)

    if can_use_terminal:
        async def _start_shell(command: str) -> ToolResult:
            terminal_id: str | None = None
            wait_task: asyncio.Task[Any] | None = None
            deferred = False
            try:
                executable, args = _shell_command(command)
                response = await connection.create_terminal(
                    session_id,
                    executable,
                    args=args,
                    cwd=str(cwd),
                )
                terminal_id = response.terminal_id
                wait_task = asyncio.create_task(
                    connection.wait_for_terminal_exit(session_id, terminal_id)
                )
                done, _ = await asyncio.wait(
                    {wait_task},
                    timeout=max(0.0, defer_threshold_seconds),
                )
                if done:
                    status = wait_task.result()
                    output = await connection.terminal_output(session_id, terminal_id)
                    content = output.output or "(no output)"
                    if output.truncated:
                        content += "\n[output truncated]"
                    await connection.release_terminal(session_id, terminal_id)
                    terminal_id = None
                    return ToolResult(
                        content=content,
                        is_error=(
                            status.exit_code not in (None, 0)
                            or status.signal is not None
                        ),
                    )
                operation = registry.add(terminal_id, command, wait_task)
                deferred = True
                return ToolResult(
                    content=(
                        f"Operation started: {operation.operation_id}. "
                        "Use check_tool, await_tool, or kill_tool."
                    )
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult(content=str(exc), is_error=True)
            finally:
                if terminal_id is not None and not deferred:
                    if wait_task is not None and not wait_task.done():
                        wait_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await wait_task
                    with contextlib.suppress(Exception):
                        await connection.release_terminal(session_id, terminal_id)

        if sys.platform == "win32":
            @tool(needs_approval=True, show_output=True)
            async def pwsh(
                command: Annotated[str, Param("PowerShell command to execute in the workspace")],
            ) -> ToolResult:
                return await _start_shell(command)

            shell_tool = pwsh
        else:
            @tool(needs_approval=True, show_output=True)
            async def bash(
                command: Annotated[str, Param("Bash command to execute in the workspace")],
            ) -> ToolResult:
                return await _start_shell(command)

            shell_tool = bash

        @tool(needs_approval=False, show_output=True)
        async def check_tool(
            handle: Annotated[str, Param("Operation ID returned by a long-running tool")],
        ) -> ToolResult:
            operation = registry.get(handle)
            if operation is None:
                return _unknown_operation(handle, registry)
            try:
                response = await connection.terminal_output(session_id, operation.terminal_id)
                status = (
                    "finished"
                    if response.exit_status is not None or operation.wait_task.done()
                    else "running"
                )
                content = f"Operation {handle} is {status}."
                if response.output:
                    content += f"\n{response.output}"
                if response.truncated:
                    content += "\n[output truncated]"
                return ToolResult(content=content)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(content=str(exc), is_error=True)

        @tool(needs_approval=False, show_output=True)
        async def await_tool(
            handle: Annotated[str, Param("Operation ID returned by a long-running tool")],
        ) -> ToolResult:
            operation = registry.get(handle)
            if operation is None:
                return _unknown_operation(handle, registry)
            try:
                status = await operation.wait_task
                output = await connection.terminal_output(session_id, operation.terminal_id)
                content = output.output or "(no output)"
                if output.truncated:
                    content += "\n[output truncated]"
                return ToolResult(content=content, is_error=status.exit_code not in (None, 0))
            except Exception as exc:  # noqa: BLE001
                return ToolResult(content=str(exc), is_error=True)
            finally:
                with contextlib.suppress(Exception):
                    await connection.release_terminal(session_id, operation.terminal_id)
                registry.release(handle)

        @tool(needs_approval=False, show_output=True)
        async def kill_tool(
            handle: Annotated[str, Param("Operation ID returned by a long-running tool")],
        ) -> ToolResult:
            operation = registry.get(handle)
            if operation is None:
                return _unknown_operation(handle, registry)
            try:
                await connection.kill_terminal(session_id, operation.terminal_id)
                return ToolResult(content=f"Operation {handle} cancelled.")
            except Exception as exc:  # noqa: BLE001
                return ToolResult(content=str(exc), is_error=True)
            finally:
                if not operation.wait_task.done():
                    operation.wait_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await operation.wait_task
                with contextlib.suppress(Exception):
                    await connection.release_terminal(session_id, operation.terminal_id)
                registry.release(handle)

        @tool(needs_approval=True)
        async def file_move(
            source: Annotated[str, Param("Source path, relative to the workspace")],
            destination: Annotated[str, Param("Destination path, relative to the workspace")],
        ) -> ToolResult:
            try:
                return await _run_file_operation(
                    connection,
                    session_id,
                    cwd,
                    "move",
                    [str(resolve_path(source)), str(resolve_path(destination))],
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult(content=str(exc), is_error=True)

        @tool(needs_approval=True)
        async def file_delete(
            path: Annotated[str, Param("File path, relative to the workspace")],
        ) -> ToolResult:
            try:
                return await _run_file_operation(
                    connection,
                    session_id,
                    cwd,
                    "delete",
                    [str(resolve_path(path))],
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult(content=str(exc), is_error=True)

        tools.extend([shell_tool, check_tool, await_tool, kill_tool, file_move, file_delete])

    return tools


def _shell_command(command: str) -> tuple[str, list[str]]:
    if sys.platform == "win32":
        return "pwsh", ["-NoProfile", "-Command", command]
    return "bash", ["-c", command]


async def _run_file_operation(
    connection: Client,
    session_id: str,
    cwd: Path,
    operation: str,
    paths: list[str],
) -> ToolResult:
    environment: list[EnvVariable] | None = None
    if sys.platform == "win32":
        if operation == "move":
            script = (
                "Move-Item -LiteralPath $env:QUACK_SOURCE "
                "-Destination $env:QUACK_DESTINATION"
            )
            environment = [
                EnvVariable(name="QUACK_SOURCE", value=paths[0]),
                EnvVariable(name="QUACK_DESTINATION", value=paths[1]),
            ]
        else:
            script = "Remove-Item -LiteralPath $env:QUACK_PATH"
            environment = [EnvVariable(name="QUACK_PATH", value=paths[0])]
        command, args = "pwsh", ["-NoProfile", "-Command", script]
    else:
        command = "mv" if operation == "move" else "rm"
        args = ["--", *paths]
    terminal = await connection.create_terminal(
        session_id,
        command,
        args=args,
        env=environment,
        cwd=str(cwd),
    )
    try:
        status = await connection.wait_for_terminal_exit(session_id, terminal.terminal_id)
        output = await connection.terminal_output(session_id, terminal.terminal_id)
        content = output.output or f"{operation.title()} completed."
        return ToolResult(content=content, is_error=status.exit_code not in (None, 0))
    finally:
        with contextlib.suppress(Exception):
            await connection.release_terminal(session_id, terminal.terminal_id)


def _unknown_operation(handle: str, registry: ACPOperationRegistry) -> ToolResult:
    return ToolResult(
        content=f"Unknown operation '{handle}'. Known operations: {registry.ids() or '(none)'}",
        is_error=True,
    )
