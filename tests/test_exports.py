"""Validate public export surfaces for quack_norris.core.agent and quack_norris.core.llm."""

from __future__ import annotations

import quack_norris.core.agent as agent_module
import quack_norris.core.llm as llm_module


# ---------------------------------------------------------------------------
# agent exports
# ---------------------------------------------------------------------------

EXPECTED_AGENT_EXPORTS = {
    "agent",
    "AgentOutput",
    "TextOutput",
    "ThinkingOutput",
    "ToolCallOutput",
    "ToolResultOutput",
}

AGENT_LLM_LEAKAGE = {
    "LLM",
    "Tool",
    "ToolResult",
    "ToolCallRequest",
    "TextDelta",
    "ThinkingDelta",
    "ChatMessage",
    "UserMessage",
    "AssistantMessage",
    "ToolResultMessage",
    "UsageInfo",
    "LLMOutput",
    "Param",
    "tool",
}


def test_agent_all_is_complete() -> None:
    """__all__ contains exactly the expected agent-owned symbols."""
    assert set(agent_module.__all__) == EXPECTED_AGENT_EXPORTS


def test_agent_all_symbols_exist() -> None:
    """Every name in __all__ is actually defined on the module."""
    for name in agent_module.__all__:
        assert hasattr(agent_module, name), f"agent.__all__ lists '{name}' but it is not defined"


def test_agent_does_not_export_llm_symbols() -> None:
    """LLM-layer symbols are NOT in agent.__all__."""
    leaked = AGENT_LLM_LEAKAGE & set(agent_module.__all__)
    assert not leaked, f"agent.__all__ leaks LLM symbols: {leaked}"


# ---------------------------------------------------------------------------
# llm exports
# ---------------------------------------------------------------------------

EXPECTED_LLM_EXPORTS = {
    "LLM",
    "CompactionConfig",
    "tool",
    "Param",
    "Tool",
    "ToolResult",
    "ApprovalState",
    "LLMOutput",
    "TextDelta",
    "ThinkingDelta",
    "ToolCallRequest",
    "UsageInfo",
    "ChatMessage",
    "UserMessage",
    "AssistantMessage",
    "ToolResultMessage",
}


def test_llm_all_is_complete() -> None:
    """llm.__all__ contains exactly the expected public symbols."""
    assert set(llm_module.__all__) == EXPECTED_LLM_EXPORTS


def test_llm_all_symbols_exist() -> None:
    """Every name in llm.__all__ is actually defined on the module."""
    for name in llm_module.__all__:
        assert hasattr(llm_module, name), f"llm.__all__ lists '{name}' but it is not defined"


def test_agent_symbols_not_in_llm_all() -> None:
    """Agent-layer output types are NOT in llm.__all__."""
    agent_only = {"AgentOutput", "TextOutput", "ThinkingOutput", "ToolCallOutput", "ToolResultOutput", "agent"}
    leaked = agent_only & set(llm_module.__all__)
    assert not leaked, f"llm.__all__ contains agent symbols: {leaked}"
