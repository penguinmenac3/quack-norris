"""Tests for context window management: tiering, safe cuts, and replay fidelity."""

from __future__ import annotations

import textwrap
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest

from quack_norris.core.context import (
    REDACTION_PLACEHOLDER,
    CheckpointOutput,
    ContextPolicy,
    apply_context_policy,
    estimate_tokens,
    find_safe_cut,
    measure,
    message_tokens,
    strip_old_tool_results,
    truncate_tool_result,
)
from quack_norris.core.llm import (
    LLM,
    AssistantMessage,
    ChatMessage,
    CheckpointMessage,
    ContextManagementConfig,
    TextDelta,
    ToolCallRequest,
    ToolResultMessage,
    UserMessage,
)
from quack_norris.core.llm.config import load_context_management_config


@pytest.fixture(autouse=True)
def _session_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect session storage to a temp dir for every test in this module."""
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))


async def _stream(*items) -> AsyncIterator:
    for item in items:
        yield item


def _yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "llms.yaml"
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# History builders
# ---------------------------------------------------------------------------

def _tool_block(i: int, calls: int = 1, output: str = "x" * 400) -> list[ChatMessage]:
    """An assistant message requesting `calls` tools, followed by their results."""
    ids = [f"c{i}_{n}" for n in range(calls)]
    assistant = AssistantMessage(
        content=f"working {i}",
        tool_calls=[
            ToolCallRequest(id=cid, name="echo", arguments={"n": cid}) for cid in ids
        ],
    )
    return [assistant, *(ToolResultMessage(tool_call_id=cid, content=output) for cid in ids)]


def _turn(i: int, calls: int = 1, output: str = "x" * 400) -> list[ChatMessage]:
    return [UserMessage(content=f"user {i}"), *_tool_block(i, calls, output)]


def _history(turns: int, **kw) -> list[ChatMessage]:
    return [m for i in range(turns) for m in _turn(i, **kw)]


def _wordy_history(turns: int) -> list[ChatMessage]:
    """History dominated by user/assistant prose, so stripping cannot save it.

    Checkpointing only kicks in once redacting tool output is not enough;
    a history of mostly tool results would just get stripped instead.
    """
    history: list[ChatMessage] = []
    for i in range(turns):
        history.append(UserMessage(content=f"user {i} " + "u" * 2000))
        history.append(AssistantMessage(
            content=f"reply {i} " + "a" * 2000,
            tool_calls=[ToolCallRequest(id=f"c{i}", name="echo", arguments={})],
        ))
        history.append(ToolResultMessage(tool_call_id=f"c{i}", content="o" * 400))
    return history


def _per_message(history: list[ChatMessage]) -> list[int]:
    return [message_tokens(m) for m in history]


def _assert_no_orphans(history: list[ChatMessage]) -> None:
    """Every tool result must be answered by a preceding assistant tool call."""
    known: set[str] = set()
    for msg in history:
        if isinstance(msg, AssistantMessage):
            known.update(tc.id for tc in msg.tool_calls)
        elif isinstance(msg, ToolResultMessage):
            assert msg.tool_call_id in known, (
                f"orphaned tool result {msg.tool_call_id!r} — providers reject this"
            )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_config_defaults(tmp_path: Path) -> None:
    p = _yaml(tmp_path, "llms:\n  - group: ollama\n    api_endpoint: http://x\n")
    assert load_context_management_config(p) == ContextManagementConfig()


def test_config_overrides(tmp_path: Path) -> None:
    p = _yaml(
        tmp_path,
        """
        context_management:
          enabled: false
          verbatim: 0.1
          checkpoint_at: 0.9
          checkpoint_reduction_rate: 0.25
          max_tool_output: 128
          summarizer_model: ollama/small
        llms: []
        """,
    )
    cfg = load_context_management_config(p)
    assert cfg == ContextManagementConfig(
        enabled=False,
        verbatim=0.1,
        checkpoint_at=0.9,
        checkpoint_reduction_rate=0.25,
        max_tool_output=128,
        summarizer_model="ollama/small",
    )


def test_config_clamps_reduction_rate(tmp_path: Path) -> None:
    """A rate of 1.0 would summarise away the newest message too."""
    p = _yaml(tmp_path, "context_management:\n  checkpoint_reduction_rate: 1.0\nllms: []\n")
    assert load_context_management_config(p).checkpoint_reduction_rate == 0.95


def test_config_ignores_unknown_sections(tmp_path: Path) -> None:
    p = _yaml(tmp_path, "something_else:\n  enabled: false\nllms: []\n")
    assert load_context_management_config(p) == ContextManagementConfig()


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def test_estimate_tokens_rounds_up() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_message_tokens_counts_tool_call_arguments() -> None:
    plain = AssistantMessage(content="hi")
    with_call = AssistantMessage(
        content="hi",
        tool_calls=[ToolCallRequest(id="c1", name="echo", arguments={"path": "x" * 200})],
    )
    assert message_tokens(with_call) > message_tokens(plain) + 40


def test_measure_includes_system_prompt_and_tool_schemas() -> None:
    from quack_norris.core.llm import Tool

    class _Big(Tool):
        name = "big"
        description = "d" * 400
        parameters = {"p": {"type": "string", "description": "q" * 400}}
        required = ["p"]

        async def execute(self, **kwargs):  # pragma: no cover - never called
            raise NotImplementedError

    history = [UserMessage(content="hi")]
    bare = measure(history, "", [], 1000)
    loaded = measure(history, "s" * 400, [_Big()], 1000)
    assert loaded.total >= bare.total + 300
    assert loaded.overhead > 0
    assert loaded.utilisation == loaded.total / 1000


# ---------------------------------------------------------------------------
# Tier 2 — stripping
# ---------------------------------------------------------------------------

def test_strip_redacts_only_outside_the_verbatim_window() -> None:
    history = _history(5)
    per = _per_message(history)
    # Roughly two turns' worth of tokens.
    verbatim = sum(per[-6:])

    redacted = strip_old_tool_results(history, per, verbatim)
    assert redacted > 0

    outputs = [m.content for m in history if isinstance(m, ToolResultMessage)]
    assert outputs[0] == REDACTION_PLACEHOLDER
    assert outputs[-1] != REDACTION_PLACEHOLDER


def test_strip_never_touches_user_or_assistant_text() -> None:
    history = _history(5)
    before = [m.content for m in history if not isinstance(m, ToolResultMessage)]
    strip_old_tool_results(history, _per_message(history), 50)
    after = [m.content for m in history if not isinstance(m, ToolResultMessage)]
    assert before == after


def test_strip_is_idempotent() -> None:
    history = _history(5)
    first = strip_old_tool_results(history, _per_message(history), 100)
    second = strip_old_tool_results(history, _per_message(history), 100)
    assert first > 0
    assert second == 0


def test_strip_keeps_per_message_sizes_in_sync() -> None:
    history = _history(4)
    per = _per_message(history)
    strip_old_tool_results(history, per, 100)
    assert per == _per_message(history)


def test_strip_noop_for_zero_window() -> None:
    history = _history(3)
    assert strip_old_tool_results(history, _per_message(history), 0) == 0


# ---------------------------------------------------------------------------
# Tier 3 — safe cuts
# ---------------------------------------------------------------------------

def test_cut_rounds_forward_past_a_tool_result_block() -> None:
    """A cut landing inside a tool-result block must swallow the whole block.

    Layout: user, assistant(A,B,C), result A, result B, result C, user, ...
    Cutting between result B and result C would orphan C.
    """
    history = [
        UserMessage(content="user 0"),
        *_tool_block(0, calls=3),
        UserMessage(content="user 1"),
        AssistantMessage(content="done"),
    ]
    per = _per_message(history)
    # Budget that lands the naive cut in the middle of the result block.
    keep = sum(per[4:])  # from "result B" onwards

    cut = find_safe_cut(history, per, keep)

    assert not isinstance(history[cut], ToolResultMessage)
    _assert_no_orphans(history[cut:])
    assert cut == 5  # whole assistant+results block dropped together


@pytest.mark.parametrize("keep", list(range(0, 400, 7)))
def test_cut_never_orphans_a_tool_result(keep: int) -> None:
    history = _history(4, calls=2)
    cut = find_safe_cut(history, _per_message(history), keep)
    _assert_no_orphans(history[cut:])


def test_cut_always_leaves_at_least_one_message() -> None:
    history = _history(3)
    cut = find_safe_cut(history, _per_message(history), 0)
    assert cut < len(history)
    assert len(history[cut:]) >= 1


def test_cut_keeps_everything_when_budget_is_ample() -> None:
    history = _history(3)
    assert find_safe_cut(history, _per_message(history), 10_000) == 0


# ---------------------------------------------------------------------------
# Per-result cap
# ---------------------------------------------------------------------------

def test_truncate_leaves_small_output_alone() -> None:
    assert truncate_tool_result("short", 100) == "short"


def test_truncate_keeps_head_and_tail() -> None:
    content = "HEAD" + ("m" * 5000) + "TAIL"
    out = truncate_tool_result(content, 100)
    assert out.startswith("HEAD")
    assert out.endswith("TAIL")
    assert "clipped" in out
    assert len(out) < len(content)


def test_truncate_mentions_the_sink_location() -> None:
    calls: list[str] = []

    def sink(text: str) -> str:
        calls.append(text)
        return "/tmp/overflow.txt"

    out = truncate_tool_result("z" * 5000, 100, sink)
    assert calls and len(calls[0]) == 5000
    assert "/tmp/overflow.txt" in out


def test_truncate_survives_a_failing_sink() -> None:
    def sink(text: str) -> str:
        raise OSError("disk full")

    out = truncate_tool_result("z" * 5000, 100, sink)
    assert "clipped" in out


# ---------------------------------------------------------------------------
# apply_context_policy
# ---------------------------------------------------------------------------

def _policy(window: int = 1000, **kw) -> ContextPolicy:
    return ContextPolicy(config=ContextManagementConfig(**kw), context_window=window)


async def _apply(history, policy, summary="SUMMARY"):
    with patch(
        "quack_norris.core.context.LLM.converse",
        return_value=_stream(TextDelta(text=summary)),
    ):
        return await apply_context_policy(
            history=history,
            policy=policy,
            model="ollama/test",
            system_prompt="sys",
            tools=[],
        )


@pytest.mark.asyncio
async def test_disabled_policy_does_nothing() -> None:
    history = _history(6)
    before = list(history)
    assert await _apply(history, _policy(enabled=False)) is None
    assert history == before


@pytest.mark.asyncio
async def test_below_threshold_strips_but_does_not_checkpoint() -> None:
    history = _history(3)
    result = await _apply(history, _policy(verbatim=0.05, checkpoint_at=0.99))
    assert result is None
    assert any(
        isinstance(m, ToolResultMessage) and m.content == REDACTION_PLACEHOLDER
        for m in history
    )


@pytest.mark.asyncio
async def test_tool_loop_defers_stripping_below_early_trigger() -> None:
    history = _history(3)
    before = [m.content for m in history if isinstance(m, ToolResultMessage)]
    policy = _policy(window=10_000, verbatim=0.05, checkpoint_at=0.8)

    result = await apply_context_policy(
        history=history,
        policy=policy,
        model="ollama/test",
        system_prompt="sys",
        tools=[],
        new_turn=False,
    )

    assert result is None
    assert [m.content for m in history if isinstance(m, ToolResultMessage)] == before


@pytest.mark.asyncio
async def test_tool_loop_strips_at_early_trigger_and_remeasures_before_checkpoint() -> None:
    history = _history(3)
    policy = _policy(window=400, verbatim=0.5, checkpoint_at=0.8)
    assert measure(history, "sys", [], policy.context_window).utilisation >= 0.9 * 0.8

    result = await apply_context_policy(
        history=history,
        policy=policy,
        model="ollama/test",
        system_prompt="sys",
        tools=[],
        new_turn=False,
    )

    assert result is None
    outputs = [m.content for m in history if isinstance(m, ToolResultMessage)]
    assert REDACTION_PLACEHOLDER in outputs
    assert measure(history, "sys", [], policy.context_window).utilisation < 0.8


@pytest.mark.asyncio
async def test_checkpoint_replaces_the_oldest_messages() -> None:
    history = _wordy_history(8)
    original_len = len(history)

    result = await _apply(history, _policy(window=10_000))

    assert isinstance(result, CheckpointOutput)
    assert isinstance(history[0], CheckpointMessage)
    assert "SUMMARY" in history[0].content
    assert len(history) < original_len
    assert result.replaced_count == original_len - len(history) + 1
    assert result.tokens_after < result.tokens_before
    _assert_no_orphans(history)


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", [0.25, 0.5, 0.75])
async def test_checkpoint_removes_the_configured_share_of_history(rate: float) -> None:
    """The cut is sized against the history, so the rate is what actually happens."""
    history = _wordy_history(40)
    before = sum(message_tokens(m) for m in history)

    result = await _apply(
        history, _policy(window=10_000, checkpoint_reduction_rate=rate),
    )

    assert result is not None
    # Measure the drop excluding the summary we just inserted, so the
    # assertion is about the cut and not about how verbose the summariser was.
    kept = sum(message_tokens(m) for m in history[1:])
    removed_share = 1.0 - (kept / before)
    assert removed_share == pytest.approx(rate, abs=0.15)
    _assert_no_orphans(history)


@pytest.mark.asyncio
async def test_small_history_is_not_over_summarised() -> None:
    """A flat summary reserve would swamp the cut and eat a short history whole."""
    history = _wordy_history(6)
    before = sum(message_tokens(m) for m in history)

    result = await _apply(
        history,
        _policy(window=200_000, checkpoint_at=0.0, checkpoint_reduction_rate=0.5),
    )

    assert result is not None
    kept = sum(message_tokens(m) for m in history[1:])
    assert kept > before * 0.3  # roughly half survives, not almost nothing


@pytest.mark.asyncio
async def test_checkpoint_is_independent_of_window_size() -> None:
    """Reduction is a share of history, so overhead and window size don't shift it."""
    a = _wordy_history(24)
    b = _wordy_history(24)

    ra = await _apply(a, _policy(window=10_000, checkpoint_reduction_rate=0.5))
    rb = await _apply(b, _policy(window=200_000, checkpoint_at=0.0,
                                 checkpoint_reduction_rate=0.5))

    assert ra is not None and rb is not None
    assert len(a) == len(b)


@pytest.mark.asyncio
async def test_checkpoints_chain_and_accumulate_replaced_count() -> None:
    history = _wordy_history(8)
    first = await _apply(history, _policy(window=10_000), summary="FIRST")
    assert first is not None

    history.extend(_wordy_history(8))
    second = await _apply(history, _policy(window=10_000), summary="SECOND")

    assert second is not None
    assert isinstance(history[0], CheckpointMessage)
    assert "SECOND" in history[0].content
    # The earlier checkpoint was folded in, so the count is cumulative.
    assert second.replaced_count > first.replaced_count
    assert any(isinstance(m, CheckpointMessage) for m in second.dropped)


@pytest.mark.asyncio
async def test_checkpoint_declines_to_resummarise_a_lone_checkpoint() -> None:
    history: list[ChatMessage] = [
        CheckpointMessage(content="c" * 4000, replaced_count=20),
        UserMessage(content="latest"),
    ]
    assert await _apply(history, _policy()) is None


@pytest.mark.asyncio
async def test_empty_summary_leaves_history_untouched() -> None:
    history = _wordy_history(8)
    before = list(history)
    assert await _apply(history, _policy(window=10_000), summary="  ") is None
    assert history == before


def test_llm_setup_exposes_context_config(tmp_path: Path) -> None:
    p = _yaml(
        tmp_path,
        "context_management:\n  verbatim: 0.15\n"
        "llms:\n  - group: ollama\n    api_endpoint: http://x\n",
    )
    LLM.setup(p)
    try:
        assert LLM.context_config().verbatim == 0.15
    finally:
        LLM._groups = {}
        LLM._model_map = {}
        LLM._configs = []
        LLM._context_config = ContextManagementConfig()
