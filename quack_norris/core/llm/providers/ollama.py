"""Ollama provider with per-model context discovery."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx2 as httpx

from quack_norris.core.llm.providers.openai import OpenAIProvider

_log = logging.getLogger(__name__)
_DEFAULT_ENDPOINT = "http://localhost:11434"


def _parse_num_ctx(parameters: Any) -> int | None:
    if not isinstance(parameters, str) or len(parameters) > 100_000:
        return None
    result = None
    for line in parameters.splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[0] != "num_ctx":
            continue
        try:
            value = int(parts[1])
        except ValueError:
            continue
        if 1 <= value <= 10_000_000:
            result = value
    return result


def _parse_model_context(model_info: Any) -> int | None:
    if not isinstance(model_info, dict):
        return None
    for key, value in model_info.items():
        if not str(key).endswith(".context_length"):
            continue
        try:
            context_length = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= context_length <= 10_000_000:
            return context_length
    return None


class OllamaProvider(OpenAIProvider):
    """Use Ollama's OpenAI API and discover Modelfile context settings."""

    def __init__(self, base_url: str = _DEFAULT_ENDPOINT) -> None:
        endpoint = base_url.rstrip("/")
        if endpoint.endswith("/v1"):
            endpoint = endpoint[:-3]
        super().__init__(base_url=f"{endpoint}/v1", api_key="ollama")
        self._native_client = httpx.AsyncClient(base_url=endpoint, timeout=5.0)
        self._context_windows: dict[str, int] = {}

    async def refresh_model_metadata(self, model_names: list[str]) -> None:
        async def refresh(model_name: str) -> None:
            try:
                response = await self._native_client.post("/api/show", json={"model": model_name})
                response.raise_for_status()
                payload = response.json()
                context_window = (
                    _parse_num_ctx(payload.get("parameters"))
                    or _parse_model_context(payload.get("model_info"))
                    if isinstance(payload, dict)
                    else None
                )
                if context_window is not None:
                    self._context_windows[model_name] = context_window
            except (httpx.HTTPError, ValueError) as exc:
                _log.warning(
                    "Could not discover context window for Ollama model '%s': %s",
                    model_name,
                    exc,
                )

        await asyncio.gather(*(refresh(model_name) for model_name in model_names))

    def context_window(self, model_name: str) -> int | None:
        return self._context_windows.get(model_name)
