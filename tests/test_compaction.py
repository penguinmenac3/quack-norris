"""Tests for history compaction: config loading and tail retention."""

from __future__ import annotations

import textwrap
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest

from quack_norris.cli.compaction import compact_history, reconstruct_tail
from quack_norris.cli.session import append_event, read_events
from quack_norris.core.llm import LLM, TextDelta, UserMessage
from quack_norris.core.llm.config import CompactionConfig, load_compaction_config


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
# CompactionConfig loading
# ---------------------------------------------------------------------------

def test_load_compaction_config_defaults(tmp_path: Path) -> None:
    p = _yaml(tmp_path, "llms:\n  - group: ollama\n    api_endpoint: http://x\n")
    cfg = load_compaction_config(p)
    assert cfg == CompactionConfig(enabled=True, threshold=0.80, target=0.30, min_turns=8)


def test_load_compaction_config_overrides(tmp_path: Path) -> None:
    p = _yaml(
        tmp_path,
        """
        compaction:
          enabled: false
          threshold: 0.5
          target: 0.1
          min_turns: 4
        llms:
          - group: ollama
            api_endpoint: http://x
        """,
    )
    cfg = load_compaction_config(p)
    assert cfg == CompactionConfig(enabled=False, threshold=0.5, target=0.1, min_turns=4)


def test_load_compaction_config_partial_overrides(tmp_path: Path) -> None:
    p = _yaml(tmp_path, "compaction:\n  threshold: 0.6\nllms: []\n")
    cfg = load_compaction_config(p)
    assert cfg.threshold == 0.6
    assert cfg.enabled is True
    assert cfg.min_turns == 8


def test_llm_setup_exposes_compaction_config(tmp_path: Path) -> None:
    p = _yaml(tmp_path, "compaction:\n  min_turns: 3\nllms:\n  - group: ollama\n    api_endpoint: http://x\n")
    LLM.setup(p)
    try:
        assert LLM.compaction_config().min_turns == 3
    finally:
        LLM._groups = {}
        LLM._model_map = {}
        LLM._configs = []
        LLM._compaction_config = CompactionConfig()


# ---------------------------------------------------------------------------
# compact_history: tail retention via target_tokens
# ---------------------------------------------------------------------------

def _seed_conversation(session_id: str, turns: int) -> None:
    """Write `turns` user/assistant event pairs to session.jsonl."""
    for i in range(turns):
        append_event(
            session_id, "user_message", {"message_id": f"m_u{i}", "text": f"user turn {i}"},
        )
        append_event(
            session_id, "content_end", {"message_id": f"m_a{i}", "text": f"assistant turn {i}"},
        )


@pytest.mark.asyncio
async def test_compact_history_no_target_summarises_everything() -> None:
    session_id = "s1"
    _seed_conversation(session_id, 5)
    chat_history = [UserMessage(content="placeholder")] * 3  # only length matters here

    with patch(
        "quack_norris.cli.compaction.LLM.converse",
        return_value=_stream(TextDelta(text="summary text")),
    ):
        new_history = await compact_history(
            chat_history=chat_history,
            model="ollama/test",
            session_id=session_id,
            trigger="manual",
        )

    # No tail kept: just the summary prefix pair.
    assert len(new_history) == 2
    assert "summary text" in new_history[0].content

    events = read_events(session_id)
    compacted = [e for e in events if e["type"] == "history_compacted"][0]
    # events[-2] is the last content_end before the history_compacted event itself
    assert compacted["data"]["cutoff_id"] == events[-2]["id"]


@pytest.mark.asyncio
async def test_compact_history_with_target_keeps_tail() -> None:
    session_id = "s2"
    _seed_conversation(session_id, 5)
    chat_history = [UserMessage(content="placeholder")] * 10

    # Budget big enough to keep roughly the last turn (user+assistant) verbatim.
    with patch(
        "quack_norris.cli.compaction.LLM.converse",
        return_value=_stream(TextDelta(text="summary text")),
    ):
        new_history = await compact_history(
            chat_history=chat_history,
            model="ollama/test",
            session_id=session_id,
            trigger="auto",
            target_tokens=20,
        )

    # summary prefix (2) + at least one verbatim tail message
    assert len(new_history) > 2
    tail_texts = [m.content for m in new_history[2:]]
    assert any("turn 4" in t for t in tail_texts)


@pytest.mark.asyncio
async def test_compact_history_target_too_small_falls_back_to_full_summary() -> None:
    """If even the single most recent event exceeds the budget, nothing survives as tail."""
    session_id = "s3"
    _seed_conversation(session_id, 3)
    chat_history = [UserMessage(content="placeholder")] * 6

    with patch(
        "quack_norris.cli.compaction.LLM.converse",
        return_value=_stream(TextDelta(text="summary text")),
    ):
        new_history = await compact_history(
            chat_history=chat_history,
            model="ollama/test",
            session_id=session_id,
            trigger="auto",
            target_tokens=1,
        )

    assert len(new_history) == 2


@pytest.mark.asyncio
async def test_compact_history_too_short_returns_unchanged() -> None:
    chat_history = [UserMessage(content="hi")]
    result = await compact_history(
        chat_history=chat_history,
        model="ollama/test",
        session_id="unused",
        trigger="manual",
    )
    assert result is chat_history


def test_reconstruct_tail_empty_for_full_cutoff() -> None:
    events = [
        {"id": 0, "type": "user_message", "data": {"text": "hi"}},
        {"id": 1, "type": "content_end", "data": {"text": "hello"}},
    ]
    assert reconstruct_tail(events, cutoff_id=1) == []


def test_reconstruct_tail_replays_events_after_cutoff() -> None:
    events = [
        {"id": 0, "type": "user_message", "data": {"text": "hi"}},
        {"id": 1, "type": "content_end", "data": {"text": "hello"}},
        {"id": 2, "type": "user_message", "data": {"text": "again"}},
        {"id": 3, "type": "content_end", "data": {"text": "sure"}},
    ]
    tail = reconstruct_tail(events, cutoff_id=1)
    assert [m.content for m in tail] == ["again", "sure"]
