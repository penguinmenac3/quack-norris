from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from quack_norris.acp.tools import ACPOperationRegistry, make_acp_tools


class FakeConnection:
    def __init__(self, files=None, *, terminal_finished: bool = True) -> None:
        self.files = dict(files or {})
        self.writes: list[tuple[str, str]] = []
        self.terminals: list[dict] = []
        self.released: list[str] = []
        self.terminal_finished = terminal_finished
        self.terminal_output_text = "terminal output"
        self.exit_event = asyncio.Event()
        if terminal_finished:
            self.exit_event.set()

    async def read_text_file(self, session_id, path, line=None, limit=None):
        content = self.files[path]
        if line is not None or limit is not None:
            lines = content.splitlines()
            start = max(0, (line or 1) - 1)
            content = "\n".join(lines[start : start + (limit or len(lines))])
        return SimpleNamespace(content=content)

    async def write_text_file(self, session_id, path, content):
        self.files[path] = content
        self.writes.append((path, content))

    async def create_terminal(
        self, session_id, command, args=None, env=None, cwd=None, output_byte_limit=None
    ):
        self.terminals.append(
            {"command": command, "args": args, "env": env, "cwd": cwd}
        )
        return SimpleNamespace(terminal_id=f"terminal-{len(self.terminals)}")

    async def wait_for_terminal_exit(self, session_id, terminal_id):
        await self.exit_event.wait()
        return SimpleNamespace(exit_code=0, signal=None)

    async def kill_terminal(self, session_id, terminal_id):
        self.exit_event.set()

    async def terminal_output(self, session_id, terminal_id):
        exit_status = (
            SimpleNamespace(exit_code=0, signal=None) if self.terminal_finished else None
        )
        return SimpleNamespace(
            output=self.terminal_output_text,
            truncated=False,
            exit_status=exit_status,
        )

    async def release_terminal(self, session_id, terminal_id):
        self.released.append(terminal_id)


@pytest.mark.asyncio
async def test_capabilities_control_acp_tool_set(tmp_path) -> None:
    tools = make_acp_tools(
        connection=FakeConnection(),
        session_id="session",
        cwd=tmp_path,
        additional_directories=(),
        can_read=True,
        can_write=False,
        can_use_terminal=False,
        registry=ACPOperationRegistry(),
    )

    assert [tool.name for tool in tools] == ["file_view"]


@pytest.mark.asyncio
async def test_exact_replace_uses_acp_read_and_write(tmp_path) -> None:
    path = str((tmp_path / "file.txt").resolve())
    connection = FakeConnection({path: "before\n"})
    tools = make_acp_tools(
        connection=connection,
        session_id="session",
        cwd=tmp_path,
        additional_directories=(),
        can_read=True,
        can_write=True,
        can_use_terminal=False,
        registry=ACPOperationRegistry(),
    )
    replace = next(tool for tool in tools if tool.name == "file_str_replace")

    result = await replace.execute(path="file.txt", old_string="before", new_string="after")

    assert result.is_error is False
    assert connection.files[path] == "after\n"


def test_shell_tool_name_matches_platform(tmp_path) -> None:
    with patch("quack_norris.acp.tools.sys.platform", "win32"):
        windows_tools = make_acp_tools(
            connection=FakeConnection(),
            session_id="session",
            cwd=tmp_path,
            additional_directories=(),
            can_read=False,
            can_write=False,
            can_use_terminal=True,
            registry=ACPOperationRegistry(),
        )
    with patch("quack_norris.acp.tools.sys.platform", "linux"):
        unix_tools = make_acp_tools(
            connection=FakeConnection(),
            session_id="session",
            cwd=tmp_path,
            additional_directories=(),
            can_read=False,
            can_write=False,
            can_use_terminal=True,
            registry=ACPOperationRegistry(),
        )

    assert windows_tools[0].name == "pwsh"
    assert unix_tools[0].name == "bash"


@pytest.mark.asyncio
async def test_fast_shell_command_returns_output_without_handle(tmp_path) -> None:
    connection = FakeConnection()
    registry = ACPOperationRegistry()
    with patch("quack_norris.acp.tools.sys.platform", "win32"):
        tools = make_acp_tools(
            connection=connection,
            session_id="session",
            cwd=tmp_path,
            additional_directories=(),
            can_read=False,
            can_write=False,
            can_use_terminal=True,
            registry=registry,
        )
        result = await tools[0].execute(command='echo "hello"')

    assert result.content == "terminal output"
    assert registry.ids() == []
    assert connection.released == ["terminal-1"]


@pytest.mark.asyncio
async def test_slow_shell_command_returns_deferred_handle(tmp_path) -> None:
    connection = FakeConnection(terminal_finished=False)
    registry = ACPOperationRegistry()
    with patch("quack_norris.acp.tools.sys.platform", "win32"):
        tools = make_acp_tools(
            connection=connection,
            session_id="session",
            cwd=tmp_path,
            additional_directories=(),
            can_read=False,
            can_write=False,
            can_use_terminal=True,
            registry=registry,
            defer_threshold_seconds=0,
        )
        result = await tools[0].execute(command="Start-Sleep 5")

    assert "Operation started: op-" in result.content
    assert len(registry.ids()) == 1
    assert connection.released == []

    handle = registry.ids()[0]
    kill = next(tool for tool in tools if tool.name == "kill_tool")
    await kill.execute(handle=handle)
    assert connection.released == ["terminal-1"]


@pytest.mark.asyncio
async def test_windows_move_passes_paths_through_environment(tmp_path) -> None:
    connection = FakeConnection()
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    with patch("quack_norris.acp.tools.sys.platform", "win32"):
        tools = make_acp_tools(
            connection=connection,
            session_id="session",
            cwd=tmp_path,
            additional_directories=(),
            can_read=False,
            can_write=False,
            can_use_terminal=True,
            registry=ACPOperationRegistry(),
        )
        move = next(tool for tool in tools if tool.name == "file_move")
        result = await move.execute(source=str(source), destination=str(destination))

    request = connection.terminals[0]
    environment = {item.name: item.value for item in request["env"]}
    assert result.is_error is False
    assert request["command"] == "pwsh"
    assert request["args"][-1] == (
        "Move-Item -LiteralPath $env:QUACK_SOURCE "
        "-Destination $env:QUACK_DESTINATION"
    )
    assert environment == {
        "QUACK_SOURCE": str(source.resolve()),
        "QUACK_DESTINATION": str(destination.resolve()),
    }
    assert connection.released == ["terminal-1"]
