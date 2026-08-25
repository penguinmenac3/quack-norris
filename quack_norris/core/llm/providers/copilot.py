"""GitHub Copilot LLM provider.

Authenticates via GitHub Device Flow (github.com or GHE), then calls the
Copilot chat-completions API with streaming.  The OAuth token is cached on
disk so subsequent runs skip the browser step.

Supports tool/function calling and streaming text the same way as
:class:`~quack_norris.core.llm.providers.openai.OpenAIProvider`.

Config example (``llms.yaml``)::

    llms:
      - group: copilot
        provider: GitHubCopilot
        api_endpoint: https://api.githubcopilot.com   # or copilot-api.<ghe-domain>
        models:
          - gpt-4.1
          - claude-sonnet-4

For GitHub Enterprise replace ``api_endpoint`` with the GHE base URL and set
``enterprise_domain`` via the ``api_key`` field (the field is repurposed as
a domain hint; the real auth token comes from the device-flow cache).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from quack_norris.core.llm.errors import LLMAPIError
from quack_norris.core.llm.provider import (
    AssistantMessage,
    ChatMessage,
    LLMOutput,
    TextDelta,
    ToolDefinition,
    ToolResultMessage,
    UsageInfo,
)
from quack_norris.core.llm.tool import ToolCallRequest


def _extract_responses_text(payload: dict[str, Any], model_name: str) -> str:
    """Pull the assistant's text out of a Responses API payload.

    ``output`` is a list of heterogeneous items — reasoning models (GPT-5+)
    typically emit a ``reasoning`` item *before* the ``message`` item that
    actually carries the text, and the ``reasoning`` item has no (or empty)
    ``content``. Scan for the first ``message`` item instead of assuming
    ``output[0]`` is it.
    """
    output = payload.get("output") or []
    for item in output:
        if item.get("type") != "message":
            continue
        parts = item.get("content") or []
        text = "".join(
            p.get("text", "") for p in parts if p.get("type") == "output_text"
        )
        if text:
            return text
        refusal = next((p.get("refusal", "") for p in parts if p.get("type") == "refusal"), "")
        if refusal:
            raise LLMAPIError(f"Model '{model_name}' refused the request: {refusal}")
    raise LLMAPIError(
        f"Copilot Responses API returned no message text for model '{model_name}' "
        f"(response: {payload!r})"
    )


def _translate_http_error(exc: Exception, model_name: str) -> LLMAPIError:
    """Translate an ``httpx`` exception into a normalised :class:`LLMAPIError`."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text
        return LLMAPIError(
            f"Copilot API error ({status}) while calling model '{model_name}': {body}",
            status_code=status,
            retryable=status == 429 or status >= 500,
        )
    if isinstance(exc, httpx.HTTPError):
        return LLMAPIError(
            f"Could not reach the Copilot API for model '{model_name}': {exc}",
            retryable=True,
        )
    return LLMAPIError(f"Copilot request to '{model_name}' failed: {exc}")


# The OAuth client-id for the quack-norris Copilot integration (same as
# copilot_client.py at the project root).
_CLIENT_ID = "Ov23li8tweQw6odWQebz"
_API_VER = "2026-06-01"
_DEFAULT_BASE_URL = "https://api.githubcopilot.com"
_GITHUB_DOMAIN = "github.com"


def _parse_endpoint(api_endpoint: str | None) -> tuple[str, str | None]:
    """Return ``(api_base_url, enterprise_domain)`` from a config ``api_endpoint``.

    Three cases:

    * ``None`` / empty → public GitHub Copilot, no enterprise domain.
    * ``https://api.githubcopilot.com`` (already the API URL) → same.
    * Any other URL, e.g. ``https://your-company.ghe.com/`` → treat as the
      GHE base, derive ``enterprise_domain`` by stripping the scheme/slashes,
      and build the API URL as ``https://copilot-api.<domain>``.
    """
    if not api_endpoint:
        return _DEFAULT_BASE_URL, None

    normalized = api_endpoint.replace("https://", "").replace("http://", "").rstrip("/")

    # Already the canonical Copilot API URL — public GitHub
    if normalized == "api.githubcopilot.com":
        return _DEFAULT_BASE_URL, None

    # GHE base URL — derive the Copilot API URL from it
    return f"https://copilot-api.{normalized}", normalized


# ---------------------------------------------------------------------------
# Token cache helpers
# ---------------------------------------------------------------------------

def _token_path(enterprise_domain: str | None) -> Path:
    suffix = f"_{enterprise_domain}" if enterprise_domain else ""
    return Path.home() / ".config/quack-norris" / f"copilot_token{suffix}"


def _load_token(enterprise_domain: str | None) -> str | None:
    p = _token_path(enterprise_domain)
    return p.read_text().strip() if p.exists() else None


def _save_token(token: str, enterprise_domain: str | None) -> None:
    p = _token_path(enterprise_domain)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token)


# ---------------------------------------------------------------------------
# Device-flow login
# ---------------------------------------------------------------------------

def _auth_urls(domain: str) -> tuple[str, str]:
    return (
        f"https://{domain}/login/device/code",
        f"https://{domain}/login/oauth/access_token",
    )


def _device_login(enterprise_domain: str | None) -> str:
    """Run GitHub Device Flow and return an OAuth access token."""
    domain = enterprise_domain or "github.com"
    device_url, token_url = _auth_urls(domain)

    r = httpx.post(
        device_url,
        headers={"Accept": "application/json"},
        json={"client_id": _CLIENT_ID, "scope": "read:user"},
    )
    r.raise_for_status()
    d = r.json()

    print(f"\n→ Open:  {d['verification_uri']}")
    print(f"→ Enter: {d['user_code']}\n")

    interval: int = d["interval"] + 3  # +3 s safety margin against clock skew
    while True:
        time.sleep(interval)
        r = httpx.post(
            token_url,
            headers={"Accept": "application/json"},
            json={
                "client_id": _CLIENT_ID,
                "device_code": d["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        data = r.json()
        if "access_token" in data:
            return data["access_token"]
        if data.get("error") == "slow_down":
            interval += 5  # RFC 8628 §3.5
        elif data.get("error") != "authorization_pending":
            raise RuntimeError(f"Copilot auth failed: {data}")


def get_copilot_token(enterprise_domain: str | None = None) -> str:
    """Return a cached Copilot OAuth token, running device-flow if needed."""
    token = _load_token(enterprise_domain)
    if token:
        return token
    token = _device_login(enterprise_domain)
    _save_token(token, enterprise_domain)
    print(f"Copilot token cached at {_token_path(enterprise_domain)}\n")
    return token


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": _API_VER,
        "Openai-Intent": "conversation-edits",
        "x-initiator": "user",
        "Content-Type": "application/json",
        "User-Agent": "quack-norris-copilot/1.0",
    }


def _use_responses_api(model: str) -> bool:
    """GPT-5+ class → Responses API; everything else → chat completions."""
    m = re.match(r"^gpt-(\d+)", model)
    return bool(m) and int(m.group(1)) >= 5 and not model.startswith("gpt-5-mini")


def _encode_messages(
    system_prompt: str,
    chat_history: list[ChatMessage],
) -> list[dict[str, Any]]:
    encoded: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
        if isinstance(msg, ToolResultMessage):
            entry["tool_call_id"] = msg.tool_call_id
        encoded.append(entry)
    return encoded


def _encode_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    result = []
    for t in tools:
        props: dict[str, Any] = {}
        for name, param in t.parameters.items():
            p: dict[str, Any] = {"type": param.type, "description": param.description}
            if param.enum:
                p["enum"] = param.enum
            props[name] = p
        result.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": t.required,
                    },
                },
            }
        )
    return result


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class CopilotProvider:
    """Streams chat completions from the GitHub Copilot API.

    Parameters
    ----------
    api_endpoint:
        Either omitted/``None`` (→ public GitHub Copilot), the canonical API
        URL ``https://api.githubcopilot.com``, or a GHE base URL such as
        ``https://your-company.ghe.com/``.  In the GHE case the Copilot API
        URL and the enterprise domain for device-flow auth are both derived
        automatically.
    """

    def __init__(self, api_endpoint: str | None = None) -> None:
        self._base_url, self._enterprise_domain = _parse_endpoint(api_endpoint)

    # ------------------------------------------------------------------
    # Internal: token (lazy, cached in memory after first use)
    # ------------------------------------------------------------------

    _token: str | None = None

    def _get_token(self) -> str:
        if self._token is None:
            self._token = get_copilot_token(self._enterprise_domain)
        return self._token

    def _clear_token(self) -> None:
        """Drop the in-memory token (forces re-auth on next call)."""
        self._token = None

    # ------------------------------------------------------------------
    # converse
    # ------------------------------------------------------------------

    async def converse(
        self,
        model_name: str,
        system_prompt: str,
        tools: list[ToolDefinition],
        chat_history: list[ChatMessage],
    ) -> AsyncIterator[LLMOutput]:
        token = self._get_token()

        if _use_responses_api(model_name):
            async for item in self._responses_api(token, model_name, system_prompt, chat_history):
                yield item
        else:
            async for item in self._chat_completions(token, model_name, system_prompt, tools, chat_history):
                yield item

    # ------------------------------------------------------------------
    # Chat completions (streaming)
    # ------------------------------------------------------------------

    async def _chat_completions(
        self,
        token: str,
        model_name: str,
        system_prompt: str,
        tools: list[ToolDefinition],
        chat_history: list[ChatMessage],
    ) -> AsyncIterator[LLMOutput]:
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": _encode_messages(system_prompt, chat_history),
            "stream": True,
        }
        if tools:
            payload["tools"] = _encode_tools(tools)

        pending_calls: dict[int, dict[str, str]] = {}

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    headers=_headers(token),
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for raw_line in response.aiter_lines():
                        if not raw_line.startswith("data: "):
                            continue
                        data = raw_line[len("data: "):]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}

                        # Text tokens
                        content = delta.get("content")
                        if content:
                            yield TextDelta(text=content)

                        # Tool call chunks
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            if idx not in pending_calls:
                                pending_calls[idx] = {
                                    "id": tc.get("id") or "",
                                    "name": (tc.get("function") or {}).get("name") or "",
                                    "arguments": "",
                                }
                            else:
                                if tc.get("id"):
                                    pending_calls[idx]["id"] = tc["id"]
                                fn = tc.get("function") or {}
                                if fn.get("name"):
                                    pending_calls[idx]["name"] = fn["name"]
                            fn = tc.get("function") or {}
                            pending_calls[idx]["arguments"] += fn.get("arguments") or ""
        except httpx.HTTPError as exc:
            raise _translate_http_error(exc, model_name) from exc

        # Emit accumulated tool calls
        for _idx in sorted(pending_calls):
            entry = pending_calls[_idx]
            try:
                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": entry["arguments"]}
            yield ToolCallRequest(id=entry["id"], name=entry["name"], arguments=args)

        yield UsageInfo(input_tokens=0, output_tokens=0)

    # ------------------------------------------------------------------
    # Responses API (GPT-5+ class, non-streaming — API doesn't stream yet)
    # ------------------------------------------------------------------

    async def _responses_api(
        self,
        token: str,
        model_name: str,
        system_prompt: str,
        chat_history: list[ChatMessage],
    ) -> AsyncIterator[LLMOutput]:
        messages = _encode_messages(system_prompt, chat_history)
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(
                    f"{self._base_url}/responses",
                    headers=_headers(token),
                    json={"model": model_name, "input": messages},
                )
                r.raise_for_status()
                text = _extract_responses_text(r.json(), model_name)
        except httpx.HTTPError as exc:
            raise _translate_http_error(exc, model_name) from exc
        except LLMAPIError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMAPIError(
                f"Could not parse Copilot Responses API reply for model '{model_name}': {exc}"
            ) from exc
        yield TextDelta(text=text)
        yield UsageInfo(input_tokens=0, output_tokens=0)
