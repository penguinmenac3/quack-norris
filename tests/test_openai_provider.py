"""Tests for OpenAIProvider error handling (rate limits, bad routes, etc.)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import openai
import pytest

from quack_norris.core.llm.errors import LLMAPIError
from quack_norris.core.llm.providers.openai import OpenAIProvider, _translate_openai_error


def _status_error(cls, status_code: int, message: str = "boom") -> openai.APIStatusError:
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    response = httpx.Response(status_code, request=request, json={"message": message})
    return cls(message, response=response, body={"message": message})


# ---------------------------------------------------------------------------
# _translate_openai_error
# ---------------------------------------------------------------------------

def test_translate_rate_limit_error() -> None:
    exc = _status_error(openai.RateLimitError, 429, "slow down")
    result = _translate_openai_error(exc, "gpt-4o")
    assert isinstance(result, LLMAPIError)
    assert result.status_code == 429
    assert result.retryable is True
    assert "gpt-4o" in result.message


def test_translate_not_found_error() -> None:
    exc = _status_error(openai.NotFoundError, 404, "no Route matched with those values")
    result = _translate_openai_error(exc, "some-model")
    assert result.status_code == 404
    assert result.retryable is False
    assert "some-model" in result.message


def test_translate_server_error_is_retryable() -> None:
    exc = _status_error(openai.InternalServerError, 500, "oops")
    result = _translate_openai_error(exc, "gpt-4o")
    assert result.status_code == 500
    assert result.retryable is True


def test_translate_connection_error() -> None:
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    exc = openai.APIConnectionError(request=request)
    exc.__cause__ = httpx.ConnectError("certificate verify failed")
    result = _translate_openai_error(exc, "gpt-4o")
    assert result.retryable is True
    assert result.status_code is None
    assert "ConnectError: certificate verify failed" in result.message


# ---------------------------------------------------------------------------
# converse() propagates a translated LLMAPIError instead of the raw SDK error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_converse_raises_llm_api_error_on_bad_route() -> None:
    provider = OpenAIProvider(base_url="http://localhost:11434/v1")
    exc = _status_error(openai.NotFoundError, 404, "no Route matched with those values")
    provider._client.chat.completions.create = AsyncMock(side_effect=exc)

    with pytest.raises(LLMAPIError) as excinfo:
        async for _ in provider.converse("bad-model", "sys", [], []):
            pass

    assert excinfo.value.status_code == 404
    assert excinfo.value.retryable is False
