"""Load LLM provider configuration.

Uses the same config format as quack-norris-2.0 so existing configs work
unchanged.  The file may be named anything (``config.yaml``, ``llms.yaml``,
etc.); only the ``llms:``, ``defaults:``, and ``compaction:`` keys are
consumed here.

:class:`~quack_norris.core.llm.llm.LLM`'s ``setup()`` merges a global config
(``~/.quack-norris/config.yaml`` or ``llms.yaml``) with a project-local one
layered on top (see :func:`merge_raw_configs`) — the local file doesn't need
to be complete; it only needs to override what differs from global.

Format::

    defaults:
      model: ollama/qwen3:14b   # default model, "group/model-name"

    llms:
      - group: ollama
        provider: OpenAI          # OpenAI | AzureOpenAI | AWSBedrock
        api_endpoint: http://localhost:11434/v1
        api_key: ollama           # optional; supports $ENV_VAR expansion
        models:                   # optional static list; omit for dynamic
          - qwen3:14b

      - group: openai
        provider: OpenAI
        api_endpoint: https://api.openai.com/v1
        api_key: ${OPENAI_API_KEY}
        models:
          - gpt-4o
          - gpt-4o-mini

      - group: nexus
        provider: AWSBedrock
        api_endpoint: https://bedrock.my-corp.example.com
        api_key: ${AWS_BEARER_TOKEN_BEDROCK}
        region: us-east-1
        models:
          - anthropic.claude-3-5-sonnet-20241022-v2:0

      - group: azure
        provider: AzureOpenAI
        api_endpoint: https://my-resource.openai.azure.com
        api_key: ${AZURE_OPENAI_KEY}
        api_version: "2024-02-01"
        models:
          - gpt-4o
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMConfig:
    """Configuration for one LLM provider entry (mirrors quack-norris-2.0)."""

    group: str
    api_endpoint: str
    provider: str = "OpenAI"
    api_key: str | None = None
    api_version: str | None = None
    region: str | None = None
    models: list[str] | None = None
    context_window: int = 128_000


@dataclass
class CompactionConfig:
    """History compaction settings, read from the ``compaction:`` key.

    Format::

        compaction:
          enabled: true      # auto-compaction on/off (manual /compact is unaffected)
          threshold: 0.80    # fraction of context window that triggers auto-compaction
          target: 0.30       # fraction of context window kept as an un-summarised tail
          min_turns: 8       # minimum chat history length before auto-compaction can trigger
    """

    enabled: bool = True
    threshold: float = 0.80
    target: float = 0.30
    min_turns: int = 8


def _resolve_env(value: str) -> str:
    """Expand ``$ENV_VAR`` / ``${ENV_VAR}`` references."""
    return os.path.expandvars(value)


def _resolve_optional(value: str | None) -> str | None:
    return _resolve_env(value) if value else value


# ---------------------------------------------------------------------------
# Raw YAML loading + merging
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict[str, Any]:
    """Read and parse *path* as YAML, returning ``{}`` for an empty file."""
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def merge_raw_configs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge *override* on top of *base* (e.g. a project-local config on a global one).

    - Keys present only in one side are kept as-is.
    - If both sides have a ``dict`` value for the same key (e.g. ``defaults``,
      ``compaction``), the dicts are merged key-by-key with *override* winning
      — so *override* doesn't need to repeat every setting.
    - Any other key present in both (including ``llms``, a list) is fully
      replaced by *override*'s value.
    """
    merged = dict(base)
    for key, value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = {**base_value, **value}
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Section parsers (operate on an already-loaded/merged raw dict)
# ---------------------------------------------------------------------------

def parse_default_model(raw: dict[str, Any]) -> str | None:
    """Return ``defaults.model`` from a raw config dict, or ``None``."""
    defaults = raw.get("defaults")
    if isinstance(defaults, dict):
        return defaults.get("model") or None
    return None


def parse_compaction_config(raw: dict[str, Any]) -> CompactionConfig:
    """Return the ``compaction:`` settings from a raw config dict.

    Missing keys/section fall back to :class:`CompactionConfig` defaults.
    """
    defaults = CompactionConfig()
    data = raw.get("compaction")
    if not isinstance(data, dict):
        return defaults

    return CompactionConfig(
        enabled=bool(data.get("enabled", defaults.enabled)),
        threshold=float(data.get("threshold", defaults.threshold)),
        target=float(data.get("target", defaults.target)),
        min_turns=int(data.get("min_turns", defaults.min_turns)),
    )


def parse_llm_configs(raw: dict[str, Any]) -> list[LLMConfig]:
    """
    Parse the ``llms:`` key of a raw config dict into :class:`LLMConfig` entries.

    Supports both list format (preferred) and the legacy dict format from
    older quack-norris configs.
    """
    llm_entries: Any = raw.get("llms", [])

    if isinstance(llm_entries, dict):
        items: list[tuple[str, dict[str, Any]]] = [
            (name, cfg) for name, cfg in llm_entries.items() if isinstance(cfg, dict)
        ]
    elif isinstance(llm_entries, list):
        items = [
            (cfg.get("group", "default"), cfg)
            for cfg in llm_entries
            if isinstance(cfg, dict)
        ]
    else:
        return []

    configs: list[LLMConfig] = []
    for group, cfg in items:
        configs.append(
            LLMConfig(
                group=group,
                api_endpoint=_resolve_env(cfg.get("api_endpoint", "")),
                provider=cfg.get("provider", "OpenAI"),
                api_key=_resolve_optional(cfg.get("api_key")),
                api_version=cfg.get("api_version"),
                region=cfg.get("region"),
                models=cfg.get("models"),
                context_window=cfg.get("context_window", 128_000),
            )
        )
    return configs


# ---------------------------------------------------------------------------
# Path-based convenience wrappers (single file, no merging)
# ---------------------------------------------------------------------------

def load_default_model(path: Path) -> str | None:
    """Return ``defaults.model`` from the config file, or ``None``."""
    try:
        return parse_default_model(load_yaml(path))
    except Exception:  # noqa: BLE001
        return None


def load_compaction_config(path: Path) -> CompactionConfig:
    """Return the ``compaction:`` settings from the config file.

    A missing or unparsable file/section returns all defaults.
    """
    try:
        return parse_compaction_config(load_yaml(path))
    except Exception:  # noqa: BLE001
        return CompactionConfig()


def load_llm_configs(path: Path) -> list[LLMConfig]:
    """Parse *path* into :class:`LLMConfig` entries (see ``parse_llm_configs``)."""
    return parse_llm_configs(load_yaml(path))
