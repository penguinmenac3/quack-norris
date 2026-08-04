"""LLM facade — routing, setup, and tool-binding logic."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from quack_norris.core.llm.config import (
    ContextManagementConfig,
    LLMConfig,
    load_yaml,
    merge_raw_configs,
    parse_context_management_config,
    parse_default_model,
    parse_llm_configs,
)
from quack_norris.core.llm.provider import (
    ChatMessage,
    LLMOutput,
    ToolDefinition,
    ToolParameter,
)
from quack_norris.core.llm.providers import AzureOpenAIProvider, BedrockProvider, CopilotProvider, OpenAIProvider
from quack_norris.core.llm.tool import Tool, ToolCallRequest, ToolResult

_DEFAULT_CONFIG_NAME = "config.yaml"
_FALLBACK_CONFIG_NAME = "llms.yaml"
_HOME_ENV_VAR = "QUACK_NORRIS_HOME"
_log = logging.getLogger(__name__)


def _global_config_dir() -> Path:
    """Return ``~/.config/quack-norris`` (or ``$QUACK_NORRIS_HOME`` if set)."""
    return Path(os.environ.get(_HOME_ENV_VAR, str(Path.home() / ".config/quack-norris")))


def _load_global_raw() -> dict[str, Any]:
    """Load the global config (``config.yaml`` or ``llms.yaml``), or ``{}`` if absent."""
    home = _global_config_dir()
    for name in (_DEFAULT_CONFIG_NAME, _FALLBACK_CONFIG_NAME):
        candidate = home / name
        if candidate.exists():
            return load_yaml(candidate)
    return {}


# Type alias for any provider instance
_AnyProvider = OpenAIProvider | BedrockProvider | CopilotProvider


def _tool_definition(t: Tool) -> ToolDefinition:
    """Convert a :class:`Tool` to the internal :class:`ToolDefinition` wire type."""
    return ToolDefinition(
        name=t.name,
        description=t.description,
        parameters={
            k: ToolParameter(
                type=v.get("type", "string"),
                description=v.get("description", ""),
                enum=v.get("enum"),
            )
            for k, v in t.parameters.items()
        },
        required=t.required,
    )


async def _safe_execute(t: Tool, kwargs: dict[str, Any]) -> ToolResult:
    try:
        return await t.execute(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(content=f"Tool execution error: {exc}", is_error=True)


def _build_provider(cfg: LLMConfig) -> _AnyProvider:
    if cfg.provider == "AzureOpenAI":
        if not cfg.api_key:
            raise ValueError(f"LLM group '{cfg.group}': AzureOpenAI requires api_key")
        if not cfg.api_version:
            raise ValueError(f"LLM group '{cfg.group}': AzureOpenAI requires api_version")
        return AzureOpenAIProvider(
            base_url=cfg.api_endpoint,
            api_key=cfg.api_key,
            api_version=cfg.api_version,
        )
    if cfg.provider == "AWSBedrock":
        return BedrockProvider(
            endpoint_url=cfg.api_endpoint,
            api_key=cfg.api_key,
            region_name=cfg.region or "us-east-1",
        )
    if cfg.provider == "GitHubCopilot":
        # api_endpoint can be omitted (public GitHub) or a GHE base URL
        # (e.g. https://your-company.ghe.com/); the provider derives
        # the Copilot API URL and auth domain automatically.
        return CopilotProvider(api_endpoint=cfg.api_endpoint or None)
    # Default: OpenAI-compatible
    return OpenAIProvider(base_url=cfg.api_endpoint, api_key=cfg.api_key)


class LLM:
    """
    Stateless facade over all configured LLM providers.

    Uses the same ``group/model`` routing as quack-norris-2.0's
    ``MultiProvider``: multiple provider entries can share the same group,
    static model lists enable fast routing, and dynamic providers (no
    ``models:`` list) are used as fallback for unknown model names.

    Call :meth:`setup` once at startup, then :meth:`converse` anywhere.
    """

    # group → list of (provider, static_models | None)
    _groups: dict[str, list[tuple[_AnyProvider, list[str] | None]]] = {}
    # group/model → provider  (pre-built from static model lists)
    _model_map: dict[str, _AnyProvider] = {}
    _configs: list[LLMConfig] = []
    _default_model: str | None = None
    _context_config: ContextManagementConfig = ContextManagementConfig()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    @classmethod
    def setup(cls, path: str | Path | None = None) -> None:
        """
        Load provider config, merging a project-local config on top of the
        global one.

        The global config (``~/.config/quack-norris/config.yaml`` or ``llms.yaml``;
        override the directory via ``$QUACK_NORRIS_HOME``) is loaded first as
        the base, if present. *path* — or, if omitted, ``config.yaml`` /
        ``llms.yaml`` in the current working directory — is then loaded and
        merged on top (see :func:`~quack_norris.core.llm.config.merge_raw_configs`):
        it doesn't need to be a complete config, only the parts that differ
        from global.

        Raises :class:`FileNotFoundError` if *path* is given explicitly but
        doesn't exist, or if neither a global nor a local config can be found.
        """
        global_raw = _load_global_raw()

        if path is not None:
            local_path: Path | None = Path(path)
            if not local_path.exists():
                raise FileNotFoundError(f"LLM config not found: {local_path}")
        else:
            local_path = None
            for name in (_DEFAULT_CONFIG_NAME, _FALLBACK_CONFIG_NAME):
                candidate = Path.cwd() / name
                if candidate.exists():
                    local_path = candidate
                    break

        local_raw = load_yaml(local_path) if local_path is not None else {}

        if not global_raw and not local_raw:
            raise FileNotFoundError(
                f"No LLM config found. Create {_DEFAULT_CONFIG_NAME} or "
                f"{_FALLBACK_CONFIG_NAME} in the current directory or in "
                f"{_global_config_dir()}, or pass the path explicitly to LLM.setup()."
            )

        raw = merge_raw_configs(global_raw, local_raw)

        configs = parse_llm_configs(raw)
        cls._configs = configs
        cls._default_model = parse_default_model(raw)
        cls._context_config = parse_context_management_config(raw)
        cls._groups = {}
        cls._model_map = {}

        for cfg in configs:
            try:
                provider = _build_provider(cfg)
            except ImportError as exc:
                _log.warning("Skipping LLM group '%s': %s", cfg.group, exc)
                continue
            group_list = cls._groups.setdefault(cfg.group, [])
            group_list.append((provider, cfg.models))

            if cfg.models is not None:
                for model in cfg.models:
                    cls._model_map[f"{cfg.group}/{model}"] = provider

    # ------------------------------------------------------------------
    # Converse
    # ------------------------------------------------------------------

    @classmethod
    async def converse(
        cls,
        model: str,
        system_prompt: str,
        tools: list[Tool],
        chat_history: list[ChatMessage],
    ) -> AsyncIterator[LLMOutput]:
        """
        Stream one conversation turn.

        Parameters
        ----------
        model:
            ``"group/model-name"`` e.g. ``"ollama/qwen3:14b"``.
            If no ``/`` is present, the first configured group is used.
        system_prompt:
            Injected as the ``system`` message.
        tools:
            :class:`~quack_norris.core.llm.tool.Tool` instances available to
            the model.  Tool definitions are derived automatically; any
            :class:`~quack_norris.core.llm.tool.ToolCallRequest` items
            yielded by the stream will have their ``execute``,
            ``needs_approval``, and ``approval_display`` attributes pre-bound
            to the matching tool.
        chat_history:
            Prior turns (not including the system message).
        """
        if not cls._groups:
            raise RuntimeError(
                "LLM.setup() has not been called. "
                "Call LLM.setup() before using LLM.converse()."
            )

        provider, model_name = cls._resolve(model)
        tool_defs = [_tool_definition(t) for t in tools]
        tool_map = {t.name: t for t in tools}
        raw_stream = provider.converse(
            model_name=model_name,
            system_prompt=system_prompt,
            tools=tool_defs,
            chat_history=chat_history,
        )
        return cls._bind_tools(raw_stream, tool_map)

    @staticmethod
    async def _bind_tools(
        raw_stream: AsyncIterator[LLMOutput],
        tool_map: dict[str, Tool],
    ) -> AsyncIterator[LLMOutput]:
        """Wrap the provider stream, binding tool callables onto ToolCallRequest items."""
        async for item in raw_stream:
            if isinstance(item, ToolCallRequest):
                matched = tool_map.get(item.name)
                if matched is not None:

                    async def _execute(
                        _t: Tool = matched,
                        **kwargs: Any,
                    ) -> ToolResult:
                        return await _safe_execute(_t, kwargs)

                    # Run pre_execute_hook before approval so the approval
                    # display and requires_approval both see normalised args
                    # (e.g. absolute project paths already rewritten to relative).
                    if matched.pre_execute_hook is not None:
                        rewritten = matched.pre_execute_hook(item.arguments)
                        if hasattr(rewritten, "__await__"):
                            rewritten = await rewritten
                        item.arguments = rewritten

                    _args = item.arguments
                    item.execute = _execute
                    item.needs_approval = matched.requires_approval(_args)
                    item.approval_display = (
                        lambda _t=matched, _a=_args: _t.approval_display(_a)
                    )
                    item.show_output = matched.show_output
                    item.truncation_allowed = matched.truncation_allowed
            yield item

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _resolve(cls, prefixed_model: str) -> tuple[_AnyProvider, str]:
        """Split ``group/model`` and return ``(provider, model_name)``."""
        # Fast path: exact match in static model map
        if prefixed_model in cls._model_map:
            _, model = prefixed_model.split("/", 1)
            return cls._model_map[prefixed_model], model

        if "/" in prefixed_model:
            group, _, model = prefixed_model.partition("/")
            if group in cls._groups:
                # Prefer dynamic providers (no static model list) as fallback
                for provider, static in cls._groups[group]:
                    if static is None:
                        return provider, model
                return cls._groups[group][0][0], model
            raise ValueError(
                f"Unknown LLM group '{group}'. "
                f"Configured groups: {list(cls._groups)}"
            )

        # No prefix — use first group's first provider
        if cls._groups:
            first = next(iter(cls._groups.values()))
            return first[0][0], prefixed_model
        raise ValueError(f"No provider found for model '{prefixed_model}'")

    @classmethod
    def groups(cls) -> list[str]:
        """Return names of all configured groups."""
        return list(cls._groups)

    @classmethod
    def configs(cls) -> list[LLMConfig]:
        """Return raw config entries (useful for context window lookups)."""
        return list(cls._configs)

    @classmethod
    def default_model(cls) -> str | None:
        """Return ``defaults.model`` from config, or ``None`` if not set."""
        return cls._default_model

    @classmethod
    def context_config(cls) -> ContextManagementConfig:
        """Return the ``context_management:`` settings from config (defaults if unset)."""
        return cls._context_config

    @classmethod
    def get_context_window(cls, prefixed_model: str) -> int:
        """Return context window size (tokens) for a model's group."""
        if "/" in prefixed_model:
            group = prefixed_model.split("/", 1)[0]
            for cfg in cls._configs:
                if cfg.group == group:
                    return cfg.context_window
        return 128_000
