"""Tests for the core agent loop (LLM mocked)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from quack_norris.core.agent import (
    AgentOutput,
    CheckpointOutput,
    ErrorOutput,
    TextOutput,
    ToolCallOutput,
    agent,
)
from quack_norris.core.context import REDACTION_PLACEHOLDER, ContextPolicy
from quack_norris.core.llm import ContextManagementConfig
from quack_norris.core.llm.errors import LLMAPIError
from quack_norris.core.llm.provider import (
    AssistantMessage,
    TextDelta,
    ToolResultMessage,
    UserMessage,
)
from quack_norris.core.llm.tool import (
    Tool,
    ToolCallRequest,
    ToolResult,
)

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


def _tool_result_contents(history) -> list[str]:
    return [
        message.content for message in history
        if isinstance(message, ToolResultMessage)
    ]


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
async def test_context_replaces_old_outputs_at_turn_start_but_defers_during_tool_loop() -> None:
    """Turn-boundary cleanup runs once; ordinary iterations keep new output intact."""
    tool = EchoTool()
    old_id, old_id_2, recent_id = "old-call", "old-call-2", "recent-call"
    old_calls = [
        ToolCallRequest(id=call_id, name="echo", arguments={"message": "old"})
        for call_id in (old_id, old_id_2)
    ]
    recent_call = ToolCallRequest(
        id=recent_id, name="echo", arguments={"message": "recent"},
    )
    history = [
        UserMessage(content="old turn"),
        AssistantMessage(content="old work", tool_calls=old_calls),
        ToolResultMessage(tool_call_id=old_id, content="o" * 40_000),
        ToolResultMessage(tool_call_id=old_id_2, content="p" * 40_000),
        UserMessage(content="recent turn"),
        AssistantMessage(content="recent work", tool_calls=[recent_call]),
        ToolResultMessage(tool_call_id=recent_id, content="recent output"),
        UserMessage(content="continue"),
    ]
    outputs: list[AgentOutput] = []
    snapshots: list[list[str]] = []
    call_count = 0
    new_output = "n" * 1_000

    async def fake_converse(model, system_prompt, tools, chat_history):
        nonlocal call_count
        call_count += 1
        snapshots.append(_tool_result_contents(chat_history))
        if call_count == 1:
            request = ToolCallRequest(
                id="new-call", name="echo", arguments={"message": new_output},
            )
            request.execute = lambda **kwargs: tool.execute(**kwargs)
            request.needs_approval = False
            return _stream(request)
        return _stream(TextDelta(text="Done"))

    policy = ContextPolicy(
        config=ContextManagementConfig(
            verbatim=0.05, checkpoint_at=0.8, max_tool_output=100_000,
        ),
        context_window=10_000,
    )
    caller_history = history

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

    assert history is caller_history
    assert snapshots[0] == [
        REDACTION_PLACEHOLDER, REDACTION_PLACEHOLDER, "recent output",
    ]
    assert snapshots[1] == [
        REDACTION_PLACEHOLDER, REDACTION_PLACEHOLDER, "recent output", new_output,
    ]


@pytest.mark.asyncio
async def test_early_context_trigger_replaces_outputs_and_remeasures_before_checkpoint() -> None:
    """Output redaction can bring a tool loop back under the checkpoint limit."""
    tool = EchoTool()
    history = [UserMessage(content="go")]
    outputs: list[AgentOutput] = []
    snapshots: list[list[str]] = []
    call_count = 0
    large_output = "x" * 28_000

    async def fake_converse(model, system_prompt, tools, chat_history):
        nonlocal call_count
        call_count += 1
        snapshots.append(_tool_result_contents(chat_history))
        if call_count in (1, 2):
            request = ToolCallRequest(
                id=f"call-{call_count}",
                name="echo",
                arguments={"message": "small"},
            )
            request.execute = (
                (lambda **kwargs: _return_result(large_output))
                if call_count == 1
                else (lambda **kwargs: _return_result("y" * 1_500))
            )
            request.needs_approval = False
            return _stream(request)
        return _stream(TextDelta(text="Done"))

    policy = ContextPolicy(
        config=ContextManagementConfig(
            verbatim=0.5, checkpoint_at=0.8, max_tool_output=100_000,
        ),
        context_window=10_000,
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

    assert snapshots[0] == []
    assert snapshots[1] == [large_output]
    assert snapshots[2] == [REDACTION_PLACEHOLDER, "y" * 1_500]
    assert not any(isinstance(output, CheckpointOutput) for output in outputs)


@pytest.mark.asyncio
async def test_checkpoint_fallback_after_replacement_preserves_tool_pairing() -> None:
    """When call arguments keep usage high, fallback checkpoints safely."""
    huge_argument = "a" * 36_000
    old_calls = [
        ToolCallRequest(id=call_id, name="echo", arguments={})
        for call_id in ("old-call", "other-old")
    ]
    history = [
        UserMessage(content="prior"),
        AssistantMessage(content="old work", tool_calls=old_calls),
        ToolResultMessage(tool_call_id="old-call", content="o" * 8_000),
        ToolResultMessage(tool_call_id="other-old", content="p" * 8_000),
        *[
            message
            for _ in range(3)
            for message in (
                UserMessage(content="u" * 3_500),
                AssistantMessage(content="a" * 3_500),
            )
        ],
        UserMessage(content="go"),
    ]
    outputs: list[AgentOutput] = []
    snapshots: list[list[str]] = []
    call_count = 0

    async def fake_converse(model, system_prompt, tools, chat_history):
        nonlocal call_count
        call_count += 1
        snapshots.append(_tool_result_contents(chat_history))
        if call_count == 1:
            request = ToolCallRequest(
                id="large-args", name="echo", arguments={"message": huge_argument},
            )
            request.execute = lambda **kwargs: _return_result("small result")
            request.needs_approval = False
            return _stream(request)
        return _stream(TextDelta(text="Done"))

    policy = ContextPolicy(
        config=ContextManagementConfig(
            verbatim=0.05, checkpoint_at=0.8, max_tool_output=100_000,
        ),
        context_window=10_000,
    )

    with (
        patch("quack_norris.core.agent.LLM.converse", side_effect=fake_converse),
        patch(
            "quack_norris.core.context._summarise",
            return_value="Earlier conversation summary",
        ),
    ):
        await agent(
            model="ollama/test",
            system_prompt="sys",
            tools=[],
            chat_history=history,
            on_permission_request=AsyncMock(return_value=True),
            on_output=_appender(outputs),
            context=policy,
        )

    checkpoints = [
        output for output in outputs if isinstance(output, CheckpointOutput)
    ]
    assert checkpoints
    assert snapshots[0] == [REDACTION_PLACEHOLDER, REDACTION_PLACEHOLDER]
    assert len(snapshots) == 2
    checkpoint_messages = [
        message for checkpoint in checkpoints for message in checkpoint.dropped
    ]
    all_messages = [*history, *checkpoint_messages]
    known_calls = {
        call.id
        for message in all_messages
        if isinstance(message, AssistantMessage)
        for call in message.tool_calls
    }
    result_ids = {
        message.tool_call_id
        for message in all_messages
        if isinstance(message, ToolResultMessage)
    }
    assert result_ids <= known_calls


async def _return_result(content: str) -> ToolResult:
    return ToolResult(content=content)


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
    """Cancellation during tool execution closes pending calls and returns interrupted text."""
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


@pytest.mark.asyncio
async def test_llm_api_error_mid_stream_emits_error_output() -> None:
    """A provider LLMAPIError is turned into an ErrorOutput instead of crashing."""
    outputs: list[AgentOutput] = []

    async def failing_stream():
        yield TextDelta(text="Hello")
        raise LLMAPIError("rate limited", status_code=429, retryable=True)

    with patch(
        "quack_norris.core.agent.LLM.converse",
        return_value=failing_stream(),
    ):
        result = await agent(
            model="ollama/test",
            system_prompt="sys",
            tools=[],
            chat_history=[UserMessage(content="hi")],
            on_permission_request=AsyncMock(return_value=True),
            on_output=_appender(outputs),
        )

    assert result == "Hello"
    errors = [o for o in outputs if isinstance(o, ErrorOutput)]
    assert len(errors) == 1
    assert "rate limited" in errors[0].message
    assert "another configured model" in errors[0].message
    assert errors[0].retryable is True


@pytest.mark.asyncio
async def test_llm_api_error_before_any_text_does_not_crash() -> None:
    """LLMAPIError raised before any text/tool output still returns cleanly."""
    outputs: list[AgentOutput] = []

    async def failing_stream():
        raise LLMAPIError("no route matched", status_code=404, retryable=False)
        yield  # pragma: no cover - makes this an async generator

    with patch(
        "quack_norris.core.agent.LLM.converse",
        return_value=failing_stream(),
    ):
        result = await agent(
            model="ollama/test",
            system_prompt="sys",
            tools=[],
            chat_history=[UserMessage(content="hi")],
            on_permission_request=AsyncMock(return_value=True),
            on_output=_appender(outputs),
        )

    assert result == ""
    errors = [o for o in outputs if isinstance(o, ErrorOutput)]
    assert len(errors) == 1
    assert errors[0].retryable is False
    assert not any(isinstance(o, TextOutput) for o in outputs)


@pytest.mark.asyncio
async def test_skill_catalog_is_sorted_and_appended_to_system_prompt() -> None:
    from quack_norris.core.agent import SkillInfo

    prompts: list[str] = []

    async def fake_converse(model, system_prompt, tools, chat_history):
        prompts.append(system_prompt)
        return _stream(TextDelta(text="Done"))

    with patch("quack_norris.core.agent.LLM.converse", side_effect=fake_converse):
        await agent(
            model="ollama/test",
            system_prompt="Base prompt.\n",
            tools=[],
            chat_history=[UserMessage(content="go")],
            on_permission_request=AsyncMock(return_value=True),
            on_output=_appender([]),
            skills=[
                SkillInfo(name="zeta", description="  Last\nskill.  "),
                SkillInfo(name="Alpha", description="First skill."),
            ],
        )

    assert prompts == [
        "Base prompt.\n\n## Available Skills\n\n"
        "- Alpha: First skill.\n"
        "- zeta: Last skill.\n\n"
        "Load a relevant skill with the skill invocation tool before following it."
    ]


@pytest.mark.asyncio
async def test_empty_skill_catalog_leaves_system_prompt_unchanged() -> None:
    prompts: list[str] = []

    async def fake_converse(model, system_prompt, tools, chat_history):
        prompts.append(system_prompt)
        return _stream(TextDelta(text="Done"))

    with patch("quack_norris.core.agent.LLM.converse", side_effect=fake_converse):
        await agent(
            model="ollama/test",
            system_prompt="Base prompt.\n",
            tools=[],
            chat_history=[UserMessage(content="go")],
            on_permission_request=AsyncMock(return_value=True),
            on_output=_appender([]),
            skills=[],
        )

    assert prompts == ["Base prompt.\n"]
