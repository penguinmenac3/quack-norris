"""Tests for the core agent loop (LLM mocked)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from quack_norris.core.agent import (
    AgentOutput,
    TextOutput,
    ToolCallOutput,
    agent,
)

from quack_norris.core.llm.provider import TextDelta, UserMessage
from quack_norris.core.llm.tool import Tool, ToolCallRequest, ToolResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _appender(lst: list) -> ...:  # type: ignore[return]
    async def _append(o: AgentOutput) -> None:
        lst.append(o)
    return _append


async def _stream(*items) -> AsyncIterator:
    for item in items:
        yield item


class EchoTool(Tool):
    name = "echo"
    description = "Echoes back the message."
    parameters = {"message": {"type": "string", "description": "Text to echo."}}
    required = ["message"]
    needs_approval = False

    async def execute(self, message: str) -> ToolResult:
        return ToolResult(content=message)


class ApprovalTool(Tool):
    name = "risky"
    description = "Needs approval."
    parameters = {}
    required = []
    needs_approval = True

    async def execute(self) -> ToolResult:
        return ToolResult(content="executed")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plain_text_response() -> None:
    """Agent returns text when LLM emits no tool calls."""
    outputs: list[AgentOutput] = []

    with patch(
        "quack_norris.core.agent.LLM.converse",
        return_value=_stream(TextDelta(text="Hello"), TextDelta(text=" world")),
    ):
        result = await agent(
            model="ollama/test",
            system_prompt="You are helpful.",
            tools=[],
            chat_history=[UserMessage(content="Hi")],
            on_permission_request=AsyncMock(return_value=True),
            on_output=_appender(outputs),
        )

    assert result == "Hello world"
    text_outputs = [o for o in outputs if isinstance(o, TextOutput)]
    assert "".join(o.text for o in text_outputs) == "Hello world"


@pytest.mark.asyncio
async def test_tool_call_then_text() -> None:
    """Agent executes a tool call then produces final text."""
    tool = EchoTool()
    outputs: list[AgentOutput] = []
    call_count = 0

    async def fake_converse(model, system_prompt, tools, chat_history):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            tc = ToolCallRequest(id="tc1", name="echo", arguments={"message": "ping"})
            tc.execute = lambda **kwargs: tool.execute(**kwargs)
            tc.needs_approval = tool.needs_approval
            return _stream(tc)
        return _stream(TextDelta(text="Done"))

    async def record(o: AgentOutput) -> None:
        outputs.append(o)

    with patch("quack_norris.core.agent.LLM.converse", side_effect=fake_converse):
        result = await agent(
            model="ollama/test",
            system_prompt="sys",
            tools=[tool],
            chat_history=[UserMessage(content="go")],
            on_permission_request=AsyncMock(return_value=True),
            on_output=record,
        )

    assert result == "Done"
    tool_calls = [o for o in outputs if isinstance(o, ToolCallOutput)]
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_name == "echo"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("truncation_allowed", "expect_clipped"),
    [(True, True), (False, False)],
)
async def test_tool_output_cap_honours_truncation_allowed(
    truncation_allowed: bool, expect_clipped: bool,
) -> None:
    """Tools whose output is instructions can opt out of the per-result cap."""
    from quack_norris.core.context import ContextPolicy
    from quack_norris.core.llm import ContextManagementConfig
    from quack_norris.core.llm.provider import ToolResultMessage

    payload = "x" * 8000
    tool = EchoTool()
    outputs: list[AgentOutput] = []
    history = [UserMessage(content="go")]
    call_count = 0

    async def fake_converse(model, system_prompt, tools, chat_history):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            tc = ToolCallRequest(id="tc1", name="echo", arguments={"message": payload})
            tc.execute = lambda **kwargs: tool.execute(**kwargs)
            tc.needs_approval = False
            tc.truncation_allowed = truncation_allowed
            return _stream(tc)
        return _stream(TextDelta(text="Done"))

    policy = ContextPolicy(
        config=ContextManagementConfig(max_tool_output=100),
        context_window=100_000,
    )

    with patch("quack_norris.core.agent.LLM.converse", side_effect=fake_converse):
        await agent(
            model="ollama/test",
            system_prompt="sys",
            tools=[tool],
            chat_history=history,
            on_permission_request=AsyncMock(return_value=True),
            on_output=_appender(outputs),
            context=policy,
        )

    results = [m for m in history if isinstance(m, ToolResultMessage)]
    assert len(results) == 1
    assert ("clipped" in results[0].content) is expect_clipped
    # The exempt path must deliver the payload whole, not merely uncut.
    if not expect_clipped:
        assert results[0].content == payload


@pytest.mark.asyncio
async def test_tool_call_denied() -> None:
    """Denied tool call results in an error result message."""
    tool = ApprovalTool()
    outputs: list[AgentOutput] = []
    call_count = 0

    async def fake_converse(model, system_prompt, tools, chat_history):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            tc = ToolCallRequest(id="tc1", name="risky", arguments={})
            tc.execute = lambda **kwargs: tool.execute(**kwargs)
            tc.needs_approval = tool.needs_approval
            return _stream(tc)
        return _stream(TextDelta(text="Understood, I won't do that."))

    with patch("quack_norris.core.agent.LLM.converse", side_effect=fake_converse):
        await agent(
            model="ollama/test",
            system_prompt="sys",
            tools=[tool],
            chat_history=[UserMessage(content="go")],
            on_permission_request=AsyncMock(return_value=False),
            on_output=_appender(outputs),
        )

    from quack_norris.core.agent import ToolResultOutput
    results = [o for o in outputs if isinstance(o, ToolResultOutput)]
    assert results[0].result.is_error is True


@pytest.mark.asyncio
async def test_cancellation_mid_stream() -> None:
    """CancelledError during LLM stream returns partial text with ---interrupted--- marker."""
    outputs: list[AgentOutput] = []

    async def cancelling_stream():
        yield TextDelta(text="Hello")
        raise asyncio.CancelledError

    with patch(
        "quack_norris.core.agent.LLM.converse",
        return_value=cancelling_stream(),
    ):
        result = await agent(
            model="ollama/test",
            system_prompt="sys",
            tools=[],
            chat_history=[UserMessage(content="hi")],
            on_permission_request=AsyncMock(return_value=True),
            on_output=_appender(outputs),
        )

    assert result == "Hello\n\n---interrupted---"
    text_outputs = [o for o in outputs if isinstance(o, TextOutput)]
    full = "".join(o.text for o in text_outputs)
    assert full == "Hello\n\n---interrupted---"


@pytest.mark.asyncio
async def test_cancellation_mid_tool_execution() -> None:
    """CancelledError during tool execution closes all pending tool calls and returns interrupted text."""
    from quack_norris.core.agent import ToolResultOutput

    outputs: list[AgentOutput] = []
    call_count = 0

    async def slow_execute(**kwargs) -> ToolResult:
        raise asyncio.CancelledError

    async def fake_converse(model, system_prompt, tools, chat_history):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            tc1 = ToolCallRequest(id="tc1", name="echo", arguments={"message": "a"})
            tc1.execute = slow_execute
            tc1.needs_approval = False
            tc2 = ToolCallRequest(id="tc2", name="echo", arguments={"message": "b"})
            tc2.execute = slow_execute
            tc2.needs_approval = False
            return _stream(TextDelta(text="Working..."), tc1, tc2)
        return _stream(TextDelta(text="Done"))

    with patch("quack_norris.core.agent.LLM.converse", side_effect=fake_converse):
        result = await agent(
            model="ollama/test",
            system_prompt="sys",
            tools=[EchoTool()],
            chat_history=[UserMessage(content="go")],
            on_permission_request=AsyncMock(return_value=True),
            on_output=_appender(outputs),
        )

    assert result == "Working...\n\n---interrupted---"
    tool_results = [o for o in outputs if isinstance(o, ToolResultOutput)]
    assert len(tool_results) == 2
    assert all(o.result.is_error for o in tool_results)
    assert all(o.result.content == "---interrupted---" for o in tool_results)
