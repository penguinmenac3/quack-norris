"""Tests for the LLM class (setup + model routing)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from quack_norris.core.llm import LLM


@pytest.fixture(autouse=True)
def _reset_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure LLM state is clean and isolated from the real ~/.quack-norris/ config."""
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


def test_setup_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        LLM.setup(tmp_path / "nonexistent.yaml")


def test_setup_registers_groups(tmp_path: Path) -> None:
    _yaml(
        tmp_path,
        """
        llms:
          - group: ollama
            api_endpoint: http://localhost:11434/v1
          - group: openai
            api_endpoint: https://api.openai.com/v1
        """,
    )
    LLM.setup(tmp_path / "llms.yaml")
    assert LLM.groups() == ["ollama", "openai"]


@pytest.mark.asyncio
async def test_converse_before_setup_raises() -> None:
    with pytest.raises(RuntimeError, match="LLM.setup()"):
        await LLM.converse("ollama/qwen3:14b", "sys", [], [])


def test_resolve_with_prefix(tmp_path: Path) -> None:
    _yaml(tmp_path, "llms:\n  - group: ollama\n    api_endpoint: http://x\n")
    LLM.setup(tmp_path / "llms.yaml")
    provider, model = LLM._resolve("ollama/qwen3:14b")
    assert model == "qwen3:14b"


def test_resolve_no_prefix_uses_first(tmp_path: Path) -> None:
    _yaml(tmp_path, "llms:\n  - group: ollama\n    api_endpoint: http://x\n")
    LLM.setup(tmp_path / "llms.yaml")
    provider, model = LLM._resolve("qwen3:14b")
    assert model == "qwen3:14b"


def test_resolve_static_model_fast_path(tmp_path: Path) -> None:
    _yaml(
        tmp_path,
        """
        llms:
          - group: openai
            api_endpoint: https://api.openai.com/v1
            models:
              - gpt-4o
              - gpt-4o-mini
        """,
    )
    LLM.setup(tmp_path / "llms.yaml")
    provider_a, model_a = LLM._resolve("openai/gpt-4o")
    provider_b, model_b = LLM._resolve("openai/gpt-4o-mini")
    assert model_a == "gpt-4o"
    assert model_b == "gpt-4o-mini"
    assert provider_a is provider_b  # same provider object


@pytest.mark.asyncio
async def test_converse_unknown_group(tmp_path: Path) -> None:
    _yaml(tmp_path, "llms:\n  - group: ollama\n    api_endpoint: http://x\n")
    LLM.setup(tmp_path / "llms.yaml")

    with pytest.raises(ValueError, match="openai"):
        stream = await LLM.converse("openai/gpt-4o", "sys", [], [])
        async for _ in stream:
            pass


def test_get_context_window(tmp_path: Path) -> None:
    _yaml(
        tmp_path,
        """
        llms:
          - group: ollama
            api_endpoint: http://localhost:11434/v1
            context_window: 32000
        """,
    )
    LLM.setup(tmp_path / "llms.yaml")
    assert LLM.get_context_window("ollama/qwen3:14b") == 32000
    assert LLM.get_context_window("unknown/model") == 128_000


# ---------------------------------------------------------------------------
# Global (~/.quack-norris/) + local config merging
# ---------------------------------------------------------------------------

def _write_global(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(home))
    p = home / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def test_setup_merges_global_and_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_global(
        monkeypatch, tmp_path,
        """
        defaults:
          model: ollama/global-model
        llms:
          - group: ollama
            api_endpoint: http://localhost:11434/v1
        """,
    )
    local = _yaml(
        tmp_path,
        """
        compaction:
          threshold: 0.5
        """,
    )
    LLM.setup(local)
    # Global llms: survive since local didn't define any.
    assert LLM.groups() == ["ollama"]
    # Global default_model survives since local didn't set defaults.model.
    assert LLM.default_model() == "ollama/global-model"
    # Local compaction.threshold overrides; unset fields keep global defaults.
    assert LLM.compaction_config().threshold == 0.5
    assert LLM.compaction_config().min_turns == 8


def test_setup_local_overrides_global_llms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_global(
        monkeypatch, tmp_path,
        """
        llms:
          - group: ollama
            api_endpoint: http://localhost:11434/v1
        """,
    )
    local = _yaml(tmp_path, "llms:\n  - group: openai\n    api_endpoint: https://api.openai.com/v1\n")
    LLM.setup(local)
    assert LLM.groups() == ["openai"]


def test_setup_uses_global_only_when_no_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_global(
        monkeypatch, tmp_path,
        """
        defaults:
          model: ollama/global-model
        llms:
          - group: ollama
            api_endpoint: http://localhost:11434/v1
        """,
    )
    # No local config.yaml/llms.yaml in cwd, and no explicit path.
    monkeypatch.chdir(tmp_path)
    LLM.setup()
    assert LLM.groups() == ["ollama"]
    assert LLM.default_model() == "ollama/global-model"


def test_setup_raises_when_neither_global_nor_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "empty-home"))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        LLM.setup()


def test_setup_explicit_path_missing_still_raises_with_global_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit --config path that doesn't exist is always an error, even
    if a global config is present."""
    _write_global(monkeypatch, tmp_path, "llms:\n  - group: ollama\n    api_endpoint: http://x\n")
    with pytest.raises(FileNotFoundError):
        LLM.setup(tmp_path / "nonexistent.yaml")
