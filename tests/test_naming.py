"""Tests for session name auto-generation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest

from quack_norris.cli.naming import generate_session_name
from quack_norris.core.llm import TextDelta


async def _stream(*items) -> AsyncIterator:
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_generate_session_name_returns_stripped_title() -> None:
    with patch(
        "quack_norris.cli.naming.LLM.converse",
        return_value=_stream(TextDelta(text='  "Fix login bug"  ')),
    ):
        name = await generate_session_name(
            "Why is login broken?", "Found the bug in auth.py", "ollama/test",
        )
    assert name == "Fix login bug"


@pytest.mark.asyncio
async def test_generate_session_name_collapses_whitespace() -> None:
    with patch(
        "quack_norris.cli.naming.LLM.converse",
        return_value=_stream(TextDelta(text="Refactor  \n  database  layer")),
    ):
        name = await generate_session_name("...", "...", "ollama/test")
    assert name == "Refactor database layer"


@pytest.mark.asyncio
async def test_generate_session_name_empty_response_returns_none() -> None:
    with patch(
        "quack_norris.cli.naming.LLM.converse",
        return_value=_stream(TextDelta(text="   ")),
    ):
        name = await generate_session_name("hi", "hello", "ollama/test")
    assert name is None


@pytest.mark.asyncio
async def test_generate_session_name_llm_error_returns_none() -> None:
    with patch(
        "quack_norris.cli.naming.LLM.converse",
        side_effect=RuntimeError("boom"),
    ):
        name = await generate_session_name("hi", "hello", "ollama/test")
    assert name is None


@pytest.mark.asyncio
async def test_generate_session_name_truncates_long_titles() -> None:
    long_title = "word " * 30
    with patch(
        "quack_norris.cli.naming.LLM.converse",
        return_value=_stream(TextDelta(text=long_title)),
    ):
        name = await generate_session_name("hi", "hello", "ollama/test")
    assert name is not None
    assert len(name) <= 60
