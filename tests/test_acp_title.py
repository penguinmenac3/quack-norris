from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest

from quack_norris.acp.title import fallback_title, generate_session_title
from quack_norris.core.llm import TextDelta


async def _stream(*items) -> AsyncIterator:
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_generate_session_title_cleans_model_output() -> None:
    with patch(
        "quack_norris.acp.title.LLM.converse",
        return_value=_stream(TextDelta(text='## "Fix Windows Move Bug."\nExtra')),
    ):
        title = await generate_session_title("Move fails", "Fixed it", "test/model")

    assert title == "Fix Windows Move Bug"


@pytest.mark.asyncio
async def test_generate_session_title_falls_back_on_error() -> None:
    with patch(
        "quack_norris.acp.title.LLM.converse",
        side_effect=RuntimeError("unavailable"),
    ):
        title = await generate_session_title(
            "Investigate why the ACP session title is not displayed correctly in the client",
            "",
            "test/model",
        )

    assert title == "Investigate why the ACP session title is not displayed..."


def test_fallback_title_normalizes_whitespace() -> None:
    assert fallback_title("  Fix\n  the   tests ") == "Fix the tests"
