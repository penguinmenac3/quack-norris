# Quack Norris

Quack Norris is three things:

1. **CLI-first coding agent** — an interactive AI assistant that runs in your terminal and works directly on your codebase (with a Web UI available as a thin relay)
2. **Agent and skill manager** (`quack-norris-manage`) — install, upgrade, and share agents and skills across projects
3. **Reusable LLM + agent core** — a zero-framework library for building your own agent implementations

## Features

- **Interactive REPL** — multi-turn chat with streaming output, slash commands, and rich input (multi-line, paste detection)
- **Non-interactive mode** — `--prompt` / `--prompt-file` for CI/CD pipelines
- **Tool execution** — shell (`pwsh`/`bash`), file operations (`file_view`, `file_write`, `file_str_replace`, `file_move`, `file_delete`), and `quack` runtime tools
- **Approval system** — three-state approval (`auto` / `whitelist→human` / `always human`); per-call dynamic decisions; glob whitelist at session, project, and global scope
- **Session management** — persistent append-only JSONL event log; resume, list, archive sessions; auto-generated session names
- **History compaction** — automatic and manual (`/compact`) summarisation when context window fills; configurable threshold/target/min-turns
- **Agent system** — load `*.agent.md` definitions from global `~/.quack-norris/agents/` or project `.agents/`; switch live with `/agent`
- **Multi-provider LLM** — Ollama, OpenAI, Azure OpenAI, AWS Bedrock, and any OpenAI-compatible endpoint
- **Background processes** — long-running shell commands promoted to background handles (`bg-xxxx`) with `check_tool` / `await_tool` / `kill_tool`

## Quick start

```bash
uv tool install quack-norris        # recommended: install as a global CLI tool

# Alternatives:
uv add quack-norris                 # add to a project (use as library)
pip install quack-norris            # plain pip
```

Copy `llms.example.yaml` to `~/.quack-norris/config.yaml` (global) and fill in your providers. You can also place a `llms.yaml` in any project directory — it will be merged on top of the global config, so you only need to specify what differs (e.g. just `defaults.model` or a different `llms:` block). Then:

```bash
quack-norris        # interactive REPL (new session in cwd)
quack-norris --resume              # pick from existing sessions
quack-norris --prompt "Summarise the auth module"   # non-interactive
```

## LLM config

Config is loaded from `~/.quack-norris/config.yaml` (global) with a project-local `llms.yaml` merged on top. `defaults` and `compaction` are merged key-by-key; `llms:` is fully replaced if the local file defines it.

```yaml
defaults:
  model: ollama/qwen3:14b

compaction:
  enabled: true
  threshold: 0.80   # auto-compact at 80 % of context window
  target: 0.30      # keep 30 % as un-summarised tail
  min_turns: 8

llms:
  - group: ollama
    provider: OpenAI
    api_endpoint: http://localhost:11434/v1
    api_key: ollama

  - group: openai
    provider: OpenAI
    api_endpoint: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    models:
      - gpt-4o
      - o3

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
```

Model strings use `group/model-name` notation — e.g. `"ollama/qwen3:14b"`, `"openai/gpt-4o"`.

## CLI flags

```bash
quack-norris [--resume [id]] [--prompt <text>] [--prompt-file <file>]
             [--project <dir>] [--archive-on-exit]
```

| Flag | Description |
|------|-------------|
| `--resume [id]` | Resume a session; omit `id` for interactive menu |
| `--prompt <text>` | Non-interactive: send one prompt, exit when done |
| `--prompt-file <file>` | Non-interactive: send file contents as prompt |
| `--project <dir>` | Start in a specific project directory |
| `--archive-on-exit` | Archive session on clean exit |

## Slash commands

| Command | Description |
|---------|-------------|
| `/agent <name>` | Switch agent definition live |
| `/model <name>` | Switch LLM live |
| `/project <dir>` | Change project working directory live |
| `/compact` | Manually trigger history compaction |
| `/archive` | Archive session and exit |
| `/help` | List all slash commands |
| `/exit` / `/quit` | Exit the REPL |

## Approval whitelist (`.quack-whitelist.yaml`)

```yaml
version: 1

pwsh:
  - pattern: "git *"
  - pattern: "uv run *"

file_str_replace:
  - pattern: "src/**"
  - pattern: "tests/**"
```

Patterns use glob syntax (`*` = any chars except `/`, `**` = any chars). Three scopes: session (in-memory), project (`.quack-whitelist.yaml`), global (`~/.quack-norris/whitelist.yaml`).

## Agent definitions

Create `*.agent.md` files in `~/.quack-norris/agents/` (global) or `<project>/.agents/` (project-scoped):

```markdown
---
name: Backend Developer
description: Focused on backend Python code
---

You are a backend developer assistant working on Python services.
Always run tests after making changes.
```

Well-known IDE files are also discovered automatically: `.github/copilot-instructions.md`, `CLAUDE.md`, `.cursor/rules`, `.github/agents/*.md`.

## Managing agents and skills (`quack-norris-manage`)

`quack-norris-manage` installs, upgrades, and removes agents and skills from git sources.

```bash
# Register a source repository
quack-norris-manage source add https://github.com/my-org/my-agents.git
quack-norris-manage source add https://github.com/my-org/my-agents.git --global
quack-norris-manage source list

# List available items (scans all registered sources)
quack-norris-manage list
quack-norris-manage list --installed          # only show installed items
quack-norris-manage list --details            # include descriptions

# Install agents and skills
quack-norris-manage install concise-writer             # auto-detects type
quack-norris-manage install concise-writer.skill       # explicit type
quack-norris-manage install planner.agent=my-planner  # install with alias
quack-norris-manage install ./my-local-skill           # local path
quack-norris-manage install concise-writer --global    # install globally

# Upgrade
quack-norris-manage upgrade                  # upgrade all installed items
quack-norris-manage upgrade concise-writer   # upgrade one item
quack-norris-manage upgrade -y               # skip confirmation

# Uninstall
quack-norris-manage uninstall concise-writer
```

Scope flags `--global` / `--local` control whether items are installed to `~/.agents/` (global, shared across projects) or `<cwd>/.agents/` (project-local). Install also accepts IDE flags (`--quack-norris`, `--copilot`, `--claude`, `--windsurf`, `--continue`) to copy agent files into IDE-specific locations.

## Core library

The `quack_norris.core` package is usable standalone — no CLI, no storage required:

```python
import asyncio
from quack_norris.core import LLM, agent
from quack_norris.core.agent import Tool, ToolResult
from quack_norris.core.llm.models import UserMessage

LLM.setup("llms.yaml")   # or LLM.setup() to search cwd / global config

final_text = await agent(
    model="ollama/qwen3:14b",
    system_prompt="You are a helpful coding assistant.",
    tools=[],
    chat_history=[UserMessage(content="Hello")],
    on_permission_request=async_fn,   # (ToolCallOutput) -> bool
    on_output=async_fn,               # (AgentOutput) -> None
)
```

`on_output` receives `AgentOutput` items: `TextOutput`, `ThinkingOutput`, `ToolCallOutput`, `ToolResultOutput`.

## Development

```bash
uv sync --extra dev
uv run python -m pytest           # all tests (excludes live tests)
uv run python -m pytest -m live   # requires a running Ollama instance
uv run ruff check quack_norris/
uv run ty check quack_norris/
```

## Documentation

See [`docs/`](docs/) for architecture, session storage, event format, CLI protocol, and agent system details.
