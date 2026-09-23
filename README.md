# 🦆 Quack Norris - the code savy star 🌟

> The harness optimized for SLMs

![A rubber duckie coding nerd](hero.png)

Quack Norris is a **compact agent core optimized for small language models (SLMs)**. It can be  integrated as an **Agent Client Protocol (ACP) agent** into other agents or UIs or used for custom code as a **Python SDK**.

## 🤖 ACP Agent

Quack Norris works with any ACP-compatible client.
To use it, install Quack Norris as a command-line tool:

```bash
uv tool install quack-norris

# Alternative from source for development
cd quack-norris
uv tool install . --force --reinstall --editable
```

Create your LLM configuration as described in [LLM configuration](#llm-configuration), then configure your ACP client (e.g. zed) to start:

```bash
quack-norris acp [--config FILE]
```

## 🧩 Python SDK

Add Quack Norris as an application dependency:

```bash
uv add quack-norris
```

The async `agent(...)` function is stateless. Your application selects the model and provides exact tool list, history, callbacks, context policy, and optional skill metadata.

```python
from pathlib import Path

from quack_norris.core import LLM, TextOutput, agent
from quack_norris.core.llm import UserMessage
from quack_norris.skills_and_agents import discover_skill_info
from quack_norris.tools import make_native_tools

# Load the configuration (described below)
LLM.setup()


# Implement your own approval logic
async def approve(_call):
    return False  # deny everything


# Stream outputs or ignore them, your choice
async def handle_output(item):
    if isinstance(item, TextOutput):
        print(item.text, end="", flush=True)


# Run the agent with tools and skills and await its final response
workspace = Path.cwd()
result = await agent(
    model=LLM.default_model() or "ollama/qwen3:14b",
    system_prompt="You are a concise coding agent.",
    tools=make_native_tools(workspace, skills=True),
    chat_history=[UserMessage(content="Review this change")],
    on_permission_request=approve,
    on_output=handle_output,
    context=None,
    skills=discover_skill_info(workspace),
)
```

<a id="llm-configuration"></a>

## ⚙️ LLM Configuration

Configuration is loaded from `~/.config/quack-norris/config.yaml`, a project-local `config.yaml`/`llms.yaml`, or a file passed with `--config` in ACP mode.

```yaml
defaults:
  model: ollama/qwen3:14b

llms:
  - group: ollama
    provider: Ollama
    api_endpoint: http://localhost:11434
```

The Ollama provider discovers each model's context length through `/api/show`, so context compaction can use the model's configured runtime window without duplicating it here. Supported providers include OpenAI-compatible endpoints, Ollama, Azure OpenAI, AWS Bedrock, and GitHub Copilot. Static model lists can be configured with `models:`; dynamic OpenAI-compatible and authenticated Copilot providers are discovered through their `/models` endpoints.

## 🛠️ Tools

Quack norris comes with a set of built-in tools to make your life easier. With ACP the tools are used if the client advertises the required capabilities, with the SDK you have control and can add, remove or replace tools as you like.

| Tool | Purpose |
|---|---|
| `file_view` | Read a file or list a directory |
| `file_write` | Create or write a text file |
| `file_str_replace` | Replace one exact text occurrence |
| `file_move` | Move a file or directory |
| `file_delete` | Delete a file or directory |
| `pwsh` / `bash` | Run a platform-appropriate shell command |
| `check_tool` | Poll a deferred operation |
| `await_tool` | Wait for a deferred operation |
| `kill_tool` | Cancel a deferred operation |
| `use_skill` | Load full skill instructions by name |

## 🔍 Diving Deeper

- [Documentation](docs/00-index.md)
- Development commands:
  ```bash
  uv run python -m pytest
  uv run ruff check .
  uv run ty check quack_norris
  ```

## ⚖️ License

[The MIT License (MIT)](LICENSE)
