from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest
from acp import PROTOCOL_VERSION, spawn_agent_process, text_block
from acp.schema import ClientCapabilities, FileSystemCapabilities, Implementation

from quack_norris.acp import QuackNorrisACPAgent, SessionStore
from quack_norris.acp.server import _tool_diff, _tool_title
from quack_norris.core import MessageEnd, TextOutput
from quack_norris.core.llm import AssistantMessage, ContextManagementConfig


class RecordingConnection:
    def __init__(self) -> None:
        self.updates: list[tuple[str, object]] = []

    async def session_update(self, session_id, update):
        self.updates.append((session_id, update))


async def scripted_agent(**kwargs) -> str:
    await kwargs["on_output"](TextOutput("Done"))
    kwargs["chat_history"].append(AssistantMessage(content="Done"))
    await kwargs["on_output"](MessageEnd(text="Done", tool_call_ids=[]))
    return "Done"


@pytest.fixture()
def configured_llm():
    with (
        patch("quack_norris.acp.server.LLM.default_model", return_value="test/model"),
        patch(
            "quack_norris.acp.server.LLM.available_models",
            return_value=["other/model", "test/model"],
        ),
        patch(
            "quack_norris.acp.server.LLM.refresh_available_models",
            new_callable=AsyncMock,
            return_value=["other/model", "test/model"],
        ),
        patch("quack_norris.acp.server.LLM.context_config", return_value=ContextManagementConfig()),
        patch("quack_norris.acp.server.LLM.get_context_window", return_value=128_000),
    ):
        yield


def test_tool_titles_and_file_diffs() -> None:
    assert _tool_title("pwsh", {"command": 'echo "hello world"'}) == (
        'pwsh: echo "hello world"'
    )
    assert _tool_title("file_write", {"path": "tmp/debug.txt"}) == "Write tmp/debug.txt"

    write_diff = _tool_diff(
        "file_write",
        {"path": "tmp/debug.txt", "content": "new content"},
    )[0]
    edit_diff = _tool_diff(
        "file_str_replace",
        {"path": "tmp/debug.txt", "old_string": "old", "new_string": "new"},
    )[0]

    assert write_diff.path == "tmp/debug.txt"
    assert write_diff.old_text is None
    assert write_diff.new_text == "new content"
    assert edit_diff.old_text == "old"
    assert edit_diff.new_text == "new"


@pytest.mark.asyncio
async def test_new_prompt_list_and_load_replay(tmp_path, monkeypatch, configured_llm) -> None:
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    project.mkdir()

    connection = RecordingConnection()
    server = QuackNorrisACPAgent(store=SessionStore(), agent_fn=scripted_agent)
    server.on_connect(connection)
    initialized = await server.initialize(
        PROTOCOL_VERSION,
        ClientCapabilities(fs=FileSystemCapabilities(), terminal=False),
        Implementation(name="tests", version="1"),
    )

    assert initialized.agent_capabilities.load_session is True
    created = await server.new_session(str(project))
    response = await server.prompt(created.session_id, [text_block("Hello")])

    assert created.modes.current_mode_id == "Quack Norris"
    config_options = {option.id: option for option in created.config_options}
    assert config_options["agent"].current_value == "Quack Norris"
    assert [option.value for option in config_options["model"].options] == [
        "other/model",
        "test/model",
    ]
    assert response.stop_reason == "end_turn"
    title_updates = [
        update
        for _, update in connection.updates
        if update.session_update == "session_info_update"
    ]
    assert title_updates[-1].title == "Hello"
    listed = await server.list_sessions(str(project))
    assert [item.session_id for item in listed.sessions] == [created.session_id]
    assert listed.sessions[0].title == "Hello"

    replay_connection = RecordingConnection()
    restarted = QuackNorrisACPAgent(store=SessionStore(), agent_fn=scripted_agent)
    restarted.on_connect(replay_connection)
    await restarted.initialize(
        PROTOCOL_VERSION,
        ClientCapabilities(),
        Implementation(name="tests", version="1"),
    )
    await restarted.load_session(str(project), created.session_id)

    replay_types = [update.session_update for _, update in replay_connection.updates]
    assert "user_message_chunk" in replay_types
    assert "agent_message_chunk" in replay_types
    assert "session_info_update" in replay_types
    assert [
        update.title
        for _, update in replay_connection.updates
        if update.session_update == "session_info_update"
    ][-1] == "Hello"


@pytest.mark.asyncio
async def test_agent_config_and_skill_command_do_not_call_model(
    tmp_path, monkeypatch, configured_llm
) -> None:
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    agent_dir = project / ".agents" / "agents"
    skill_dir = project / ".agents" / "skills" / "testing"
    agent_dir.mkdir(parents=True)
    skill_dir.mkdir(parents=True)
    (agent_dir / "reviewer.agent.md").write_text("Review carefully.", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("Use tests.", encoding="utf-8")

    calls = 0

    async def counting_agent(**kwargs):
        nonlocal calls
        calls += 1
        return ""

    connection = RecordingConnection()
    server = QuackNorrisACPAgent(agent_fn=counting_agent)
    server.on_connect(connection)
    await server.initialize(
        PROTOCOL_VERSION,
        ClientCapabilities(),
        Implementation(name="tests", version="1"),
    )
    created = await server.new_session(str(project))
    config_options = {option.id: option for option in created.config_options}
    assert "reviewer" in [option.value for option in config_options["agent"].options]

    await server.set_config_option("agent", created.session_id, "reviewer")
    await server.prompt(created.session_id, [text_block("/skills")])
    with patch("quack_norris.acp.server.LLM.reload") as reload_config:
        await server.prompt(created.session_id, [text_block("/refresh")])
    await server.set_config_option("model", created.session_id, "other/model")

    reload_config.assert_called_once_with()

    assert calls == 0
    assert server._sessions[created.session_id].selected_agent == "reviewer"
    assert server._sessions[created.session_id].model == "other/model"
    messages = [
        update.content.text
        for _, update in connection.updates
        if update.session_update == "agent_message_chunk"
    ]
    assert any("testing" in message for message in messages)


@pytest.mark.asyncio
async def test_real_stdio_launcher_initializes_and_lists_sessions(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(
        "defaults:\n"
        "  model: test/model\n"
        "llms:\n"
        "  - group: test\n"
        "    provider: OpenAI\n"
        "    api_endpoint: http://127.0.0.1:1/v1\n"
        "    api_key: fake\n"
        "    models: [model]\n",
        encoding="utf-8",
    )
    client = RecordingConnection()
    environment = dict(os.environ)
    environment["QUACK_NORRIS_HOME"] = str(tmp_path / "home")

    async with spawn_agent_process(
        client,
        sys.executable,
        "-m",
        "quack_norris.acp",
        "--config",
        str(config),
        env=environment,
        cwd=project,
    ) as (connection, process):
        initialized = await connection.initialize(
            PROTOCOL_VERSION,
            ClientCapabilities(),
            Implementation(name="tests", version="1"),
        )
        created = await connection.new_session(str(project))
        listed = await connection.list_sessions(str(project))

        assert process.returncode is None
        assert initialized.agent_info.name == "quack-norris"
        assert [session.session_id for session in listed.sessions] == [created.session_id]


def test_session_store_rejects_unsafe_session_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))
    store = SessionStore()

    assert store.load("../outside") is None
    assert store.load(str(tmp_path / "absolute")) is None


@pytest.mark.asyncio
async def test_cancel_normalizes_prompt_response(tmp_path, monkeypatch, configured_llm) -> None:
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    project.mkdir()
    started = asyncio.Event()

    async def blocking_agent(**kwargs):
        started.set()
        await asyncio.Event().wait()
        return ""

    connection = RecordingConnection()
    server = QuackNorrisACPAgent(agent_fn=blocking_agent)
    server.on_connect(connection)
    await server.initialize(
        PROTOCOL_VERSION,
        ClientCapabilities(),
        Implementation(name="tests", version="1"),
    )
    created = await server.new_session(str(project))
    prompt_task = asyncio.create_task(server.prompt(created.session_id, [text_block("wait")]))
    await started.wait()

    await server.cancel(created.session_id)
    response = await prompt_task

    assert response.stop_reason == "cancelled"
    assert server._store.load(created.session_id).chat_history[0].content == "wait"
