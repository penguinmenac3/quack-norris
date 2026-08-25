"""Tests for the CopilotProvider and its registration in LLM."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from quack_norris.core.llm import LLM
from quack_norris.core.llm.errors import LLMAPIError
from quack_norris.core.llm.provider import TextDelta, ToolDefinition, UsageInfo
from quack_norris.core.llm.providers.copilot import (
    CopilotProvider,
    _load_token,
    _parse_endpoint,
    _save_token,
    _token_path,
    _translate_http_error,
    _use_responses_api,
)
from quack_norris.core.llm.tool import ToolCallRequest


# ---------------------------------------------------------------------------
# _use_responses_api
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model,expected", [
    ("gpt-4o", False),
    ("gpt-4.1", False),
    ("gpt-5", True),
    ("gpt-5-mini", False),        # explicitly excluded
    ("gpt-10", True),
    ("claude-sonnet-4", False),
])
def test_use_responses_api(model: str, expected: bool) -> None:
    assert _use_responses_api(model) is expected


# ---------------------------------------------------------------------------
# Token cache helpers
# ---------------------------------------------------------------------------

def test_token_path_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    p = _token_path(None)
    assert p == tmp_path / ".config/quack-norris" / "copilot_token"


def test_token_path_enterprise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    p = _token_path("your-company.ghe.com")
    assert p == tmp_path / ".config/quack-norris" / "copilot_token_your-company.ghe.com"


# ---------------------------------------------------------------------------
# _parse_endpoint
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("endpoint,expected_base,expected_domain", [
    (None,                                   "https://api.githubcopilot.com", None),
    ("",                                     "https://api.githubcopilot.com", None),
    ("https://api.githubcopilot.com",        "https://api.githubcopilot.com", None),
    ("https://your-company.ghe.com/",       "https://copilot-api.your-company.ghe.com", "your-company.ghe.com"),
    ("https://your-company.ghe.com",        "https://copilot-api.your-company.ghe.com", "your-company.ghe.com"),
    ("https://company.ghe.com/",             "https://copilot-api.company.ghe.com",        "company.ghe.com"),
])
def test_parse_endpoint(
    endpoint: str | None,
    expected_base: str,
    expected_domain: str | None,
) -> None:
    base, domain = _parse_endpoint(endpoint)
    assert base == expected_base
    assert domain == expected_domain


def test_save_and_load_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert _load_token(None) is None
    _save_token("tok-abc", None)
    assert _load_token(None) == "tok-abc"


# ---------------------------------------------------------------------------
# CopilotProvider — chat completions streaming
# ---------------------------------------------------------------------------

def _sse_lines(*payloads: dict[str, Any], done: bool = True) -> list[str]:
    """Build SSE lines for the mock aiter_lines response."""
    lines = [f"data: {json.dumps(p)}" for p in payloads]
    if done:
        lines.append("data: [DONE]")
    return lines


def _make_chunk(content: str | None = None, tool_calls: list | None = None) -> dict:
    delta: dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    return {"choices": [{"delta": delta}]}


@pytest.fixture()
def provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CopilotProvider:
    """A CopilotProvider with a pre-loaded token (no device flow)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _save_token("test-token", None)
    return CopilotProvider()


def _make_stream_mock(lines: list[str]) -> tuple[MagicMock, MagicMock]:
    """Return (mock_client, mock_response) with aiter_lines yielding *lines*."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    # aiter_lines() must return an async iterable, not a coroutine
    mock_response.aiter_lines = lambda: aiter_from(lines)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_client, mock_response


@pytest.mark.asyncio
async def test_converse_text(provider: CopilotProvider) -> None:
    lines = _sse_lines(
        _make_chunk("Hello"),
        _make_chunk(", world"),
    )
    mock_client, _ = _make_stream_mock(lines)

    with patch("quack_norris.core.llm.providers.copilot.httpx.AsyncClient", return_value=mock_client):
        items = []
        async for item in provider.converse("gpt-4.1", "sys", [], []):
            items.append(item)

    texts = [i.text for i in items if isinstance(i, TextDelta)]
    assert texts == ["Hello", ", world"]
    assert any(isinstance(i, UsageInfo) for i in items)


@pytest.mark.asyncio
async def test_converse_tool_call(provider: CopilotProvider) -> None:
    tool_chunk_1 = _make_chunk(tool_calls=[
        {"index": 0, "id": "call-1", "function": {"name": "my_tool", "arguments": '{"x"'}},
    ])
    tool_chunk_2 = _make_chunk(tool_calls=[
        {"index": 0, "function": {"arguments": ': 42}'}},
    ])
    lines = _sse_lines(tool_chunk_1, tool_chunk_2)
    mock_client, _ = _make_stream_mock(lines)

    with patch("quack_norris.core.llm.providers.copilot.httpx.AsyncClient", return_value=mock_client):
        items = []
        async for item in provider.converse("gpt-4.1", "sys", [], []):
            items.append(item)

    tool_calls = [i for i in items if isinstance(i, ToolCallRequest)]
    assert len(tool_calls) == 1
    assert tool_calls[0].id == "call-1"
    assert tool_calls[0].name == "my_tool"
    assert tool_calls[0].arguments == {"x": 42}


def _responses_stub(client: MagicMock, response_json: dict) -> None:
    mock_r = MagicMock()
    mock_r.raise_for_status = MagicMock()
    mock_r.json = MagicMock(return_value=response_json)
    client.post = AsyncMock(return_value=mock_r)


@pytest.mark.asyncio
async def test_converse_responses_api(provider: CopilotProvider) -> None:
    """GPT-5 class uses the Responses API (non-streaming)."""
    response_json = {
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "I am GPT-5."}]},
        ],
    }

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    _responses_stub(mock_client, response_json)

    with patch("quack_norris.core.llm.providers.copilot.httpx.AsyncClient", return_value=mock_client):
        items = []
        async for item in provider.converse("gpt-5", "sys", [], []):
            items.append(item)

    texts = [i.text for i in items if isinstance(i, TextDelta)]
    assert texts == ["I am GPT-5."]


@pytest.mark.asyncio
async def test_converse_responses_api_skips_leading_reasoning_item(
    provider: CopilotProvider,
) -> None:
    """Reasoning models emit a ``reasoning`` item (no text) before the ``message`` item."""
    response_json = {
        "output": [
            {"type": "reasoning", "content": []},
            {"type": "message", "content": [{"type": "output_text", "text": "Reasoned answer."}]},
        ],
    }

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    _responses_stub(mock_client, response_json)

    target = "quack_norris.core.llm.providers.copilot.httpx.AsyncClient"
    with patch(target, return_value=mock_client):
        items = []
        async for item in provider.converse("gpt-5", "sys", [], []):
            items.append(item)

    texts = [i.text for i in items if isinstance(i, TextDelta)]
    assert texts == ["Reasoned answer."]


@pytest.mark.asyncio
async def test_converse_responses_api_no_message_item_raises_llm_api_error(
    provider: CopilotProvider,
) -> None:
    """No ``message`` item in ``output`` → a clean LLMAPIError, not an IndexError."""
    response_json = {"output": [{"type": "reasoning", "content": []}]}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    _responses_stub(mock_client, response_json)

    target = "quack_norris.core.llm.providers.copilot.httpx.AsyncClient"
    with patch(target, return_value=mock_client), pytest.raises(LLMAPIError):
        async for _ in provider.converse("gpt-5", "sys", [], []):
            pass


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------

def test_translate_http_status_error() -> None:
    request = httpx.Request("POST", "https://api.githubcopilot.com/chat/completions")
    response = httpx.Response(429, request=request, text="rate limited")
    exc = httpx.HTTPStatusError("429", request=request, response=response)
    result = _translate_http_error(exc, "gpt-4.1")
    assert isinstance(result, LLMAPIError)
    assert result.status_code == 429
    assert result.retryable is True
    assert "gpt-4.1" in result.message


def test_translate_http_connect_error() -> None:
    request = httpx.Request("POST", "https://api.githubcopilot.com/chat/completions")
    exc = httpx.ConnectError("connection refused", request=request)
    result = _translate_http_error(exc, "gpt-4.1")
    assert result.status_code is None
    assert result.retryable is True


@pytest.mark.asyncio
async def test_converse_raises_llm_api_error_on_bad_status(provider: CopilotProvider) -> None:
    request = httpx.Request("POST", "https://api.githubcopilot.com/chat/completions")
    response = httpx.Response(404, request=request, text="no Route matched with those values")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("404", request=request, response=response)
    )
    mock_response.aiter_lines = lambda: aiter_from([])

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=False)

    target = "quack_norris.core.llm.providers.copilot.httpx.AsyncClient"
    with patch(target, return_value=mock_client), pytest.raises(LLMAPIError) as excinfo:
        async for _ in provider.converse("gpt-4.1", "sys", [], []):
            pass

    assert excinfo.value.status_code == 404
    assert excinfo.value.retryable is False


# ---------------------------------------------------------------------------
# LLM.setup integration — GitHubCopilot provider type
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))
    LLM._groups = {}
    LLM._model_map = {}
    LLM._configs = []
    yield
    LLM._groups = {}
    LLM._model_map = {}
    LLM._configs = []


def _yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "llms.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def test_setup_copilot_minimal(tmp_path: Path) -> None:
    """No api_endpoint → defaults to public GitHub Copilot URL."""
    _yaml(
        tmp_path,
        """
        llms:
          - group: copilot
            provider: GitHubCopilot
        """,
    )
    LLM.setup(tmp_path / "llms.yaml")
    provider, _ = LLM._resolve("copilot/gpt-4.1")
    assert isinstance(provider, CopilotProvider)
    assert provider._base_url == "https://api.githubcopilot.com"



    _yaml(
        tmp_path,
        """
        llms:
          - group: copilot
            provider: GitHubCopilot
            api_endpoint: https://api.githubcopilot.com
            models:
              - gpt-4.1
              - claude-sonnet-4
        """,
    )
    LLM.setup(tmp_path / "llms.yaml")
    assert "copilot" in LLM.groups()


def test_setup_copilot_provider_instance(tmp_path: Path) -> None:
    _yaml(
        tmp_path,
        """
        llms:
          - group: copilot
            provider: GitHubCopilot
            api_endpoint: https://api.githubcopilot.com
            models:
              - gpt-4.1
        """,
    )
    LLM.setup(tmp_path / "llms.yaml")
    provider, model = LLM._resolve("copilot/gpt-4.1")
    assert isinstance(provider, CopilotProvider)
    assert model == "gpt-4.1"


def test_setup_copilot_ghe(tmp_path: Path) -> None:
    """GHE base URL → API URL and enterprise domain derived automatically."""
    _yaml(
        tmp_path,
        """
        llms:
          - group: copilot
            provider: GitHubCopilot
            api_endpoint: https://your-company.ghe.com/
            models:
              - gpt-4.1
        """,
    )
    LLM.setup(tmp_path / "llms.yaml")
    provider, _ = LLM._resolve("copilot/gpt-4.1")
    assert isinstance(provider, CopilotProvider)
    assert provider._enterprise_domain == "your-company.ghe.com"
    assert provider._base_url == "https://copilot-api.your-company.ghe.com"


# ---------------------------------------------------------------------------
# Utility: async iterator from a plain list
# ---------------------------------------------------------------------------

async def aiter_from(items: list) -> None:  # type: ignore[return]
    """Yield items from a list as an async iterator."""
    for item in items:
        yield item
