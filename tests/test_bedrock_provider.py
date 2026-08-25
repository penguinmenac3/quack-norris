"""Tests for BedrockProvider error translation."""

from __future__ import annotations

from quack_norris.core.llm.errors import LLMAPIError
from quack_norris.core.llm.providers.bedrock import _translate_bedrock_error


class _FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError's shape without importing boto3."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(f"{code}: {message}")
        self.response = {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": status_code},
        }


def test_translate_throttling_is_retryable() -> None:
    exc = _FakeClientError("ThrottlingException", "Too many requests", 429)
    result = _translate_bedrock_error(exc, "anthropic.claude-3")
    assert isinstance(result, LLMAPIError)
    assert result.retryable is True
    assert result.status_code == 429
    assert "anthropic.claude-3" in result.message


def test_translate_client_error_not_retryable() -> None:
    exc = _FakeClientError("ValidationException", "bad input", 400)
    result = _translate_bedrock_error(exc, "anthropic.claude-3")
    assert result.retryable is False
    assert result.status_code == 400


def test_translate_5xx_is_retryable_even_without_known_code() -> None:
    exc = _FakeClientError("SomeNewException", "server blew up", 503)
    result = _translate_bedrock_error(exc, "anthropic.claude-3")
    assert result.retryable is True


def test_translate_unstructured_exception_falls_back() -> None:
    exc = ConnectionError("network unreachable")
    result = _translate_bedrock_error(exc, "anthropic.claude-3")
    assert isinstance(result, LLMAPIError)
    assert result.status_code is None
    assert result.retryable is False
    assert "anthropic.claude-3" in result.message
