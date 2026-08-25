# Quack Norris

Quack Norris is a compact agent core optimized for small language models. It can be embedded as a Python SDK or exposed as an Agent Client Protocol (ACP) agent.

```mermaid
flowchart LR
    App[Python application] -->|agent(...)| Core[Stateless agent core]
    Client[ACP client] -->|ACP| Server[Quack Norris ACP server]
    Server --> Core
    Server --> Tools[ACP-backed tools]
    Server --> SA[skills_and_agents]
    Core --> LLM[LLM providers]
```

## Packages

| Package | Responsibility |
|---|---|
| `quack_norris.core` | Stateless model/tool loop, context management and LLM providers |
| `quack_norris.tools` | Native filesystem, terminal and operation tools for SDK hosts |
| `quack_norris.skills_and_agents` | Persona/skill discovery, skill invocation and management |
| `quack_norris.acp` | ACP server, durable sessions, commands and ACP-backed tools |

The previous interactive chat CLI and Web UI are no longer product entry points. Use an ACP-compatible client to interact with `quack-norris acp`.

## Python SDK

```python
from quack_norris.core import agent
from quack_norris.core.llm import UserMessage

history = [UserMessage(content="Review this change")]
result = await agent(
    model="ollama/qwen3:14b",
    system_prompt="You are a concise coding agent.",
    tools=my_tools,
    chat_history=history,
    on_permission_request=approve,
    on_output=handle_output,
    context=context_policy,
    skills=skills,
)
```

`agent(...)` is stateless: callers provide the exact tool list, history, callbacks, context policy and optional compact skill metadata. It never injects operation tools or persists sessions.

## ACP agent

```text
quack-norris acp [--config FILE]
```

The ACP server provides:

- initialize, new, prompt and cancel;
- durable session list/load with history replay;
- capability-aware filesystem and terminal tools;
- permission requests through the ACP client;
- persona selection through ACP session modes and an `agent` config option;
- model selection through an ACP `model` config option, including dynamic OpenAI-compatible and authenticated Copilot `/models` discovery;
- skill commands and `/refresh` for live selector/discovery updates;
- generated session titles with deterministic fallback;
- project/global persisted approval choices;
- terminal fast-path completion before deferred operation handles;
- per-session terminal operation registries.

ACP stdout is protocol-only. Diagnostics use stderr.

## Tools

ACP mode assembles tools from client capabilities:

- `file_view`, `file_write`, `file_str_replace` from ACP filesystem callbacks (`file_str_replace` is non-atomic because ACP has no compare-and-swap);
- `file_move` and `file_delete` through ACP terminal callbacks;
- `pwsh` on Windows or `bash` elsewhere, plus `check_tool`, `await_tool` and `kill_tool` through ACP terminals;
- `use_skill` through local skill discovery.

SDK hosts may use the included native tools or pass custom tools directly.

## Personas and skills

Discovery uses the existing locations:

- agents: `~/.agents/agents/*.agent.md` and `<cwd>/.agents/agents/*.agent.md`;
- skills: `~/.agents/skills/<name>/SKILL.md` and `<cwd>/.agents/skills/<name>/SKILL.md`;
- well-known project instructions including `CLAUDE.md` and `.github/agents/*.md`.

Compact skill names/descriptions are appended to the system prompt only when supplied to `agent(..., skills=...)`. Full instructions are loaded on demand through `use_skill`.

Management remains available through:

```text
quack-norris-manage --help
```

## LLM configuration

Configuration is loaded from `~/.config/quack-norris/config.yaml` or a file passed with `--config`.

```yaml
defaults:
  model: ollama/qwen3:14b

llms:
  - group: ollama
    provider: OpenAI
    api_endpoint: http://localhost:11434/v1
    api_key: ollama
    context_window: 32768
```

Supported providers include OpenAI-compatible endpoints, Azure OpenAI, AWS Bedrock and GitHub Copilot.

## Development

```text
uv run python -m pytest
uv run ruff check .
```

Live tests require their external services and are marked `live`.

## Architecture

Current architecture and package documentation starts at [docs/00-index.md](docs/00-index.md).
