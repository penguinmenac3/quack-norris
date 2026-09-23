"""Tests for Ollama model metadata discovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from quack_norris.core.llm.providers.ollama import (
    OllamaProvider,
    _parse_model_context,
    _parse_num_ctx,
)


def test_parse_num_ctx() -> None:
    assert _parse_num_ctx("temperature 0.2\nnum_ctx 16384\nnum_batch 128") == 16384
    assert _parse_num_ctx("num_ctx invalid") is None
    assert _parse_num_ctx({"num_ctx": 16384}) is None


def test_parse_model_context() -> None:
    assert _parse_model_context({"qwen3.context_length": 40960}) == 40960
    assert _parse_model_context({"qwen3.context_length": "invalid"}) is None
    assert _parse_model_context(None) is None


@pytest.mark.asyncio
async def test_refresh_model_metadata_discovers_context_window() -> None:
    provider = OllamaProvider("http://localhost:11434/v1")
    await provider._native_client.aclose()
    response = MagicMock()
    response.json.return_value = {"parameters": "temperature 0.2\nnum_ctx 8192"}
    provider._native_client = MagicMock()
    provider._native_client.post = AsyncMock(return_value=response)

    await provider.refresh_model_metadata(["quack-qwen"])

    assert provider.context_window("quack-qwen") == 8192
    response.raise_for_status.assert_called_once_with()
    provider._native_client.post.assert_awaited_once_with(
        "/api/show", json={"model": "quack-qwen"}
    )


@pytest.mark.asyncio
async def test_refresh_uses_model_maximum_when_num_ctx_is_unset() -> None:
    provider = OllamaProvider("http://localhost:11434")
    await provider._native_client.aclose()
    response = MagicMock()
    response.json.return_value = {
        "parameters": "temperature 0.2",
        "model_info": {"qwen3.context_length": 40960},
    }
    provider._native_client = MagicMock()
    provider._native_client.post = AsyncMock(return_value=response)

    await provider.refresh_model_metadata(["quack-qwen"])

    assert provider.context_window("quack-qwen") == 40960
