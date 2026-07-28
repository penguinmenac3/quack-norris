# Agent System

## Overview

The agent runs inside the CLI process. There is no agent pool manager, no IPC bridge, no separate agent subprocess — the CLI process *is* the agent process. One CLI process = one session = one agent.

---

## Agent Loop

When a user message is received (from stdin or socket), the agent loop runs:

```
1. Apply any config delta from the message (agent, model, cwd)
2. Load whitelist rules (session + project + global)
3. Build system prompt from agent definition
4. Repair history (fix orphaned tool calls from previous crashes)
5. Fit history to context window (summarise if needed)
6. Call LLM (streaming)
     → emit content_start
     → emit content_delta (per chunk)
     → collect tool calls if any
7. No tool calls?
     → emit content_end (compacts start + deltas)
     → loop exits (agent idle)
8. Tool calls present?
     → emit content_end
     → for each tool call:
          → check whitelist
          → emit tool_call_start
          → if needs_approval: wait for tool_call_approved / tool_call_denied
          → execute tool (or emit synthetic error if denied)
          → emit tool_call_result (compacts start + approved/denied)
     → add results to history
     → go to step 5
```

All `emit` operations write to `session.jsonl` and broadcast to connected socket clients.

### Context Management

History is kept within the context window by `core/context.py`, which runs before **every** LLM call — including between tool-calling iterations, where a single turn can otherwise blow the window on its own. Walking backwards from the newest message, history is tiered:

1. **Verbatim (short-term).** The newest `verbatim` share of the window stays completely intact.
2. **Stripped (mid-term).** Everything older keeps its user and assistant text but has tool outputs replaced with a redaction placeholder. The agent can re-run the tool if it needs the output again.
3. **Checkpoint (long-term).** Once utilisation reaches `checkpoint_at`, the oldest `checkpoint_reduction_rate` of the history is summarised into a `CheckpointMessage`.

The reduction rate is a share of the **history**, not of the window. Sizing it against the history means a checkpoint always removes a predictable amount of what is actually there, regardless of window size or how much of it the system prompt and tool schemas consume.

Each call: measure system prompt + tool schemas + history → strip → checkpoint only if still over. Stripping alone keeps most sessions under the threshold indefinitely, so summarisation is rare.

Two invariants matter:

- **Cuts never orphan a tool result.** Cut points are rounded forward past `ToolResultMessage`s, so an assistant message and all of its results are dropped as one block. A result whose `tool_call_id` no longer appears in the history is rejected outright by providers.
- **The system prompt is always included, never trimmed.**

Individual tool results are separately capped at `max_tool_output` tokens, keeping head *and* tail (stack traces and exit codes live at the end); the CLI spills the full text to `<session>/overflow/` and points the agent at the path.

Raw events remain in `session.jsonl` permanently and are visible in the Web UI history view, regardless of what the LLM context currently holds.

Configurable in `~/.quack-norris/config.yaml`. `verbatim` and `checkpoint_at` are fractions of the model's `context_window`; `checkpoint_reduction_rate` is a fraction of the history:

```yaml
context_management:
  enabled: true                   # set to false to disable automatic management entirely
  verbatim: 0.30                  # newest slice kept fully intact
  checkpoint_at: 0.80             # utilisation that triggers a checkpoint
  checkpoint_reduction_rate: 0.5  # share of the history a checkpoint summarises away
  max_tool_output: 4096           # per-result cap in tokens
  summarizer_model: null          # null = use the conversation's model
```

A tool can opt out of the `max_tool_output` cap with `@tool(truncation_allowed=False)`. This is for tools whose output is *instructions* rather than data — `use_skill`, for instance — where a clipped result is worse than none, because the model has no way to tell it is following half a procedure. Exempt output is still redacted wholesale once it ages out of the verbatim window, which is safe: the model can simply load it again.

The user can also checkpoint manually with `/compact` at the `> ` prompt (see [04-cli.md](04-cli.md)).

### History Repair

Before each LLM call, the agent scans history for orphaned tool calls (tool_call_start without a matching tool_call_result). These occur when the process was killed mid-execution. Each orphan is patched with a synthetic `tool_call_result` (is_error: true, result: "---interrupted---") so the LLM context is valid.

### Stopping

When `cmd_agent_stop` is received via socket (or Ctrl+C in the terminal), the agent loop is cancelled via asyncio task cancellation. On cancellation:

1. Current LLM stream is closed; partial text is closed with `\n\n---interrupted---`
2. Any pending tool calls get synthetic error results
3. `content_end` is emitted with the interrupted text
4. `meta.json` is updated: `status: idle`
5. Socket clients see the session return to idle

The session is always left in a clean state — no open streams, no pending tool calls.

---

## Agent Definition

Agents are defined in `*.agent.md` files discovered on startup.

### Format

```markdown
---
name: Backend Developer
description: Focused on backend Python code
---

You are a backend developer assistant working on Python services.
Your working directory is the project root.
Always run tests after making changes.
```

Frontmatter is optional YAML. The body is the system prompt, injected verbatim at the start of every LLM call.

### Discovery

Agent files are discovered from:
1. `~/.quack-norris/agents/` — global agents
2. `<project-root>/.agents/` — project-scoped agents
3. Skills (`SKILL.md` files in `skills/` directories) contribute context, not agents

Project-scoped agents take precedence for name collisions. Names include scope prefix when ambiguous: `my-app/Backend Developer` vs global `Backend Developer`.

### System Prompt Stability

The system prompt is static — no runtime data is injected. This maximises LLM prompt cache hits. Runtime context (available agents, projects, skills) is discovered on demand via the `quack` tool.

---

## Tools

The agent has exactly three tools. This is intentional — a small, orthogonal set covering everything without overlap.

| Tool | Responsibility | Needs Approval |
|------|---------------|----------------|
| `bash` / `pwsh` | Run shell commands | Yes |
| `text_editor` | Structured file operations | Yes (write/edit/move/delete only) |
| `quack` | Runtime interaction — ask user, spawn agents, load skills | Partial |

### `bash` / `pwsh`

Runs shell commands. Named `bash` on Linux/Mac, `pwsh` on Windows — the name signals to the LLM which shell syntax to use. Supports full shell features: pipelines, chaining, redirects.

Approval is required. Whitelist patterns apply.

### `text_editor`

Structured file operations. Used for multiline content where shell quoting would be fragile.

| Subcommand | Approval |
|------------|----------|
| `view` | No |
| `write` | Yes |
| `str_replace` | Yes |
| `move` | Yes (except `/tmp/quack_*` — pre-whitelisted) |
| `delete` | Yes (except `/tmp/quack_*` — pre-whitelisted) |

`write` fails if the file already exists. It writes content to `/tmp/quack_<hash>` and returns an error explaining what happened. The agent can then use `str_replace` to edit in place, or `move` the temp file if overwrite was intentional.

### `quack`

Reaches into the Quack runtime. Four subcommands, each prints a help if the args are not correct or if `--help` is passed:

**`ask-user`** — ask the user a question:
```
quack ask-user "Which branch should I target?"
quack ask-user "How should I proceed?" --choices "Refactor" "Fix in place" "Skip"
```
The CLI prints the question and waits for the user to type a response (or select a choice). No approval needed.

**`agent`** — interact with other agents:
```
quack agent --list                      # list available agents
quack agent "my-app/Planner"            # hand conversation over
quack agent "my-app/Planner" --subagent-task "Refactor auth"    # run subagent, block until done
```
Without subagent task it transfers the full session to the named agent. With `--subagent-task` it spawns a fresh session, blocks until done, returns the result. Both require approval.

**`skill`** — load a skill into context:
```
quack skill --list             # list available skills
quack skill "concise-writer"   # load skill (appends skill content to system prompt)
```
No approval needed.

**`project`** — set the working project:
```
quack project --list           # list available projects
quack project "my-app"         # set project root (updates cwd)
```
Requires approval.

---

## Approval System

### Decision Point

The agent checks the whitelist before emitting `tool_call_start`. If whitelisted, it sets `needs_approval: false` and execution proceeds without user interaction.

### Whitelist Check Order

```
In-memory session rules (from tool_call_approved with scope: session)
  → .quack-whitelist.yaml in project root (scope: project)
    → ~/.quack-norris/whitelist.yaml (scope: global)
      → show approval UI
```

All three layers are loaded once at session start. Session-scoped rules accumulate in memory and are gone when the process exits.

### Pattern Matching

- `*` — matches any characters except `/`
- `**` — matches any characters including `/`
- `bash` / `pwsh` patterns match the full command string
- `text_editor` patterns match the file path, relative to project root
- `quack agent` / `quack project` patterns match the name argument
- Case-sensitive on Linux/Mac, case-insensitive on Windows

### Whitelist File Format

```yaml
version: 1

bash:
  - pattern: "git *"
  - pattern: "uv run *"
  - pattern: "npm run *"

text_editor:
  - pattern: "src/**"
  - pattern: "tests/**"

quack:
  - pattern: "my-app/*"
```

### Pipeline Decomposition

When a `bash` command contains a pipeline, the approval system decomposes it and checks each component:

| Operator | Behaviour |
|----------|-----------|
| `\|` | Split into individual piped commands, check each |
| `&&`, `\|\|`, `;` | Split into chained commands, check each |
| `$(...)`, `` `...` ``, `(...)` | Cannot decompose safely → always require approval |

The full pipeline runs without approval only if every component is whitelisted. If multiple components need approval, they appear together in a single card.

### Pattern Suggestions

`suggested_patterns` in `tool_call_start` is generated by the LLM at the time the tool call is made. The LLM understands context and proposes semantically meaningful patterns (e.g. `curl https://api.github.com/repos/owner/*` for a specific GitHub API call), not just naive string splits. Patterns go from most specific to most permissive.

---

## LLM Integration

The agent communicates with LLMs via HTTP using the OpenAI-compatible API. Configuration lives in `~/.quack-norris/config.yaml`.

### Provider Support

- **Ollama** — local models (default)
- **OpenAI** — cloud
- **Azure OpenAI** — enterprise cloud
- Any OpenAI-compatible endpoint

### Config Format

```yaml
llms:
  - name: "ollama/granite4:micro-h"
    provider: ollama
    base_url: http://localhost:11434
    model: granite4:micro-h

  - name: "openai/gpt-4o"
    provider: openai
    api_key: ${OPENAI_API_KEY}
    model: gpt-4o

default_llm: "ollama/granite4:micro-h"
default_agent: "Quack Norris"
```

The `default_llm` and `default_agent` are used when no override is specified in the session or the user message.

---

Last Updated: 2026-07-09
