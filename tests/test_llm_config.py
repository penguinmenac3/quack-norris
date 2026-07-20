"""Tests for LLM config loading."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from quack_norris.core.llm.config import (
    load_llm_configs,
    merge_raw_configs,
    parse_default_model,
)


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "llms.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def test_load_basic(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        llms:
          - group: ollama
            api_endpoint: http://localhost:11434/v1
            api_key: ollama
            models:
              - qwen3:14b
        """,
    )
    configs = load_llm_configs(p)
    assert len(configs) == 1
    assert configs[0].group == "ollama"
    assert configs[0].api_endpoint == "http://localhost:11434/v1"
    assert configs[0].models == ["qwen3:14b"]


def test_load_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "llms.yaml"
    p.write_text("")
    configs = load_llm_configs(p)
    assert configs == []


def test_load_no_llms_key(tmp_path: Path) -> None:
    p = _write(tmp_path, "defaults:\n  model: ollama/qwen3:14b\n")
    configs = load_llm_configs(p)
    assert configs == []


def test_env_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_KEY", "secret-key")
    p = _write(
        tmp_path,
        """
        llms:
          - group: openai
            api_endpoint: https://api.openai.com/v1
            api_key: ${TEST_KEY}
        """,
    )
    configs = load_llm_configs(p)
    assert configs[0].api_key == "secret-key"


def test_multiple_groups(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        llms:
          - group: ollama
            api_endpoint: http://localhost:11434/v1
          - group: openai
            api_endpoint: https://api.openai.com/v1
        """,
    )
    configs = load_llm_configs(p)
    assert [c.group for c in configs] == ["ollama", "openai"]


def test_provider_types(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        llms:
          - group: nexus
            provider: AWSBedrock
            api_endpoint: https://bedrock.example.com
            region: us-east-1
          - group: azure
            provider: AzureOpenAI
            api_endpoint: https://res.openai.azure.com
            api_key: key
            api_version: "2024-02-01"
        """,
    )
    configs = load_llm_configs(p)
    assert configs[0].provider == "AWSBedrock"
    assert configs[0].region == "us-east-1"
    assert configs[1].provider == "AzureOpenAI"
    assert configs[1].api_version == "2024-02-01"


def test_full_config_yaml_ignored_keys(tmp_path: Path) -> None:
    """A full config.yaml with other keys works — only llms: is consumed."""
    p = _write(
        tmp_path,
        """
        defaults:
          model: ollama/qwen3:14b
          agent: Quack Norris
        workspace_roots:
          - ~/projects
        llms:
          - group: ollama
            api_endpoint: http://localhost:11434/v1
        """,
    )
    configs = load_llm_configs(p)
    assert len(configs) == 1
    assert configs[0].group == "ollama"


# ---------------------------------------------------------------------------
# defaults.model
# ---------------------------------------------------------------------------

def test_parse_default_model() -> None:
    assert parse_default_model({"defaults": {"model": "ollama/qwen3:14b"}}) == "ollama/qwen3:14b"


def test_parse_default_model_missing_section() -> None:
    assert parse_default_model({}) is None
    assert parse_default_model({"defaults": {}}) is None


def test_parse_default_model_ignores_legacy_flat_key() -> None:
    """The old flat `default_model:` key is no longer recognised."""
    assert parse_default_model({"default_model": "ollama/qwen3:14b"}) is None


# ---------------------------------------------------------------------------
# merge_raw_configs
# ---------------------------------------------------------------------------

def test_merge_raw_configs_override_extends_base() -> None:
    base = {"defaults": {"model": "ollama/a"}, "compaction": {"threshold": 0.8, "min_turns": 8}}
    override = {"compaction": {"threshold": 0.5}}
    merged = merge_raw_configs(base, override)
    assert merged["defaults"] == {"model": "ollama/a"}
    assert merged["compaction"] == {"threshold": 0.5, "min_turns": 8}


def test_merge_raw_configs_override_replaces_lists() -> None:
    base = {"llms": [{"group": "ollama"}]}
    override = {"llms": [{"group": "openai"}]}
    merged = merge_raw_configs(base, override)
    assert merged["llms"] == [{"group": "openai"}]


def test_merge_raw_configs_keys_only_in_one_side() -> None:
    base = {"llms": [{"group": "ollama"}]}
    override = {"defaults": {"model": "ollama/a"}}
    merged = merge_raw_configs(base, override)
    assert merged["llms"] == [{"group": "ollama"}]
    assert merged["defaults"] == {"model": "ollama/a"}


def test_merge_raw_configs_empty_override_keeps_base() -> None:
    base = {"defaults": {"model": "ollama/a"}, "llms": [{"group": "ollama"}]}
    assert merge_raw_configs(base, {}) == base


def test_merge_raw_configs_empty_base_uses_override() -> None:
    override = {"defaults": {"model": "ollama/a"}}
    assert merge_raw_configs({}, override) == override
