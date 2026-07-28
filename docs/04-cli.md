# CLI

## Overview

`quack-norris chat` is the primary interface. It runs the agent loop directly in the process, writes events to the session file, and serves a TCP socket for Web UI relay. It has two modes:

- **Interactive** (default) — multi-turn REPL, full approval flow, persistent session
- **Non-interactive** (`--prompt-file` / `--prompt`) — one prompt, auto-deny approvals, exits when done

Both modes use the same codebase. The mode only changes the input/approval/exit behaviour.

---

## Command

```bash
quack-norris chat [--resume <id>] [--prompt-file <file>] [--prompt <text>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--resume [id]` | (interactive menu) | Session ID to resume. Skips selection menu. |
| `--prompt-file <file>` | — | Send file contents as the first and only message. Enables non-interactive mode. |
| `--prompt <text>` | — | Inline prompt. Enables non-interactive mode. |
| `--archive-on-exit` | — | Directly archives a session when it exits (usefull for CI/CD sessions with --prompt) |

`--prompt-file` and `--prompt` are mutually exclusive.

---

## Startup

### Session selection

If `--resume` is not given, the CLI starts a new session in the current working directory with default settings.

If `--resume` is gevin without an id, it shows the sessions based on the files existing in `~/.quack-norris/sessions/`. Only unarchived sessions are listed, capped at 50 most-recent:

```
QuackNorris

  [1] Auth refactor          (idle,    2 min ago)
  [2] API refactoring        (working, 5 min ago)
  [3] Documentation          (idle,    18 hours ago)

Select [1-3]:
```

Selecting an existing session attaches to it. If the session is `blocked` (approval pending), the approval card is shown immediately.

Before resuming a session, the agent checks if the session is already alive. If it is so it shows an error and does not resume it but tells the user to close it in the other cli or webui.

---

## Startup Sequence (both modes)

1. Determine session ID (new UUID or from `--resume`)
2. Create `~/.quack-norris/sessions/<id>/` if new
3. Check if session is already alive if not new (-> quit with error if already alive)
4. Write or read `session.jsonl`
5. Open TCP socket on `127.0.0.1:0` (OS assigns port)
6. Write `meta.json` with `pid`, `port`, `owner`, `status: idle`
7. If resuming: replay `session.jsonl` to reconstruct history for the agent loop
8. If terminal: print history to stdout (last N messages, configurable)
9. Enter interactive loop or send non-interactive prompt

---

## Interactive Mode

### Chat flow

The `> ` prompt appears only when the agent is idle. Input is not accepted while the agent is working.

```
> Hi

Hello! How can I help you today?

> Can you check the tests?

Sure, running them now...

  bash: uv run pytest
  [auto-approved]

42 passed in 1.23s. All tests pass.

> _
```

### Sending a message

User types at `> ` and presses Enter. The CLI:
1. Appends `user_message` event to `session.jsonl`
2. Forwards event to any connected socket clients
3. Updates `meta.json` (status: working)
4. Runs agent loop
5. On completion: updates `meta.json` (status: idle), shows `> ` prompt

### Tool calls

Tool calls are printed inline during agent output:

```
  bash: git commit -m "Fix login bug"
  [auto-approved]

  text_editor: str_replace src/auth/login.py
  [approved]

  bash: curl https://external-api.com/data
  [denied]
```

`tool_call_result` content is not printed — the agent's subsequent response summarises the outcome. Errors are printed.

### Slash commands

Slash commands are processed at the `> ` prompt before the agent sees them. They are not sent as user messages.

| Command | Description |
|---------|-------------|
| `/agent <name>` | Switch agent immediately |
| `/model <name>` | Switch model immediately |
| `/project <cwd>` | Change project working directory immediately |
| `/compact` | Checkpoint the conversation history immediately |
| `/help` | List slash commands |

Config changes (`/agent`, `/model`, `/project`) apply **immediately**:
- `meta.json` is rewritten at once (if the session exists on disk)
- A `system_hint` event is appended to `session.jsonl` so the agent sees the change in its LLM context without being prompted to respond
- If no user message has been sent yet, config is held in memory only — no session directory is created

`/compact` checkpoints immediately regardless of token count, appends a `checkpoint` event, and prints how many messages were summarised and the token delta.

---

## Stopping and Exiting

### Ctrl+C while agent is working

Appends `cmd_agent_stop` handling internally. Agent loop is cancelled. Prints `Stopping...`. Waits for the agent to write `content_end` with `---interrupted---`. Prompt reappears.

### Ctrl+C while idle / `/exit` / `/quit`

Exits the CLI. Session persists. Meta.json `pid`/`port` become stale (the Web UI server handles this gracefully).
We should consider putting a null in pid and port, so others do not need to check (faster startup).

```
(Ctrl+C)
Bye.
```

### Connection lost (Web UI spawned process)

If the Web UI server disconnects from the socket and the process was `owner: webui`, the CLI continues running. The Web UI server will reconnect when the next client opens `GET /chat/<id>`.

---

## Approval Flow (Interactive Mode)

When `tool_call_start` with `needs_approval: true` is written to the log, the `> ` prompt is replaced by an approval card:

```
Approval needed: bash
Command: git commit -m "Fix login bug"

  [y] Allow once
  [p] Allow pattern...
  [n] Deny
> _
```

### Allow once (`y`)

Appends `tool_call_approved` (no pattern). Agent continues.

### Deny (`n`)

Appends `tool_call_denied`. Agent receives synthetic error result.

### Allow pattern (`p`)

CLI shows AI-suggested patterns (from `suggested_patterns` in the `tool_call_start` event):

```
Allow future commands matching:

  [1] git commit -m "Fix login bug"   (exact)
  [2] git commit *                    (any git commit)
  [3] git *                           (any git command)
  [c] Custom pattern

> _
```

Then scope:

```
Scope:
  [s] This session  (in-memory only)
  [p] This project  (.quack-whitelist.yaml)
  [g] Always        (~/.quack-norris/whitelist.yaml)

> _
```

Appends `tool_call_approved` with `pattern` and `scope`. Backend saves the rule. Agent continues.

### Multiple unapproved commands (pipeline)

When a pipeline has multiple commands that need approval, one card covers all:

```
Approval needed: bash
Command: tail -5 foo | curl https://api.x.com | jq .name

Requires approval for:
  • curl https://api.x.com
  • jq .name

  [y] Allow once (all)
  [p] Allow pattern... (per command)
  [n] Deny
> _
```

`p` presents a pattern picker for each command in sequence.

---

## Non-Interactive Mode

```bash
quack-norris chat --prompt-file task.md > result.md
quack-norris chat --prompt "Summarise the auth module"
```

Behaviour:
- Sends prompt as single user message
- Streams agent response to stdout
- All approval requests are auto-denied (logged to stderr: `[auto-denied] bash: ...`)
- Exits with code 0 when agent reaches idle
- Exits with code 1 on connection error or agent error

No `> ` prompt, no approval interaction, no slash commands.

---

## Socket Protocol

The CLI opens a TCP server on `127.0.0.1:0` at startup. The assigned port is written to `meta.json`.

### Connections

The socket accepts multiple simultaneous connections (e.g. Web UI server + monitoring tool). Each connection is independent.

### Output (CLI → client)

On connection: CLI replays full `session.jsonl` as newline-delimited JSON events, then streams live events as they are appended. Each line is one complete JSON event (same format as `session.jsonl`).

```
{"id":0,"type":"session_created","ts":"...","data":{...}}\n
{"id":1,"type":"user_message","ts":"...","data":{...}}\n
{"id":2,"type":"content_end","ts":"...","data":{...}}\n
... (replay complete, now live)
{"id":3,"type":"user_message","ts":"...","data":{...}}\n
```

### Input (client → CLI)

Clients send commands as newline-delimited JSON (same `cmd_*` types as in [03-event-format.md](03-event-format.md)):

```
{"type":"cmd_user_message","data":{"message_id":"m_005","text":"Hi","config":null}}\n
```

Commands are processed in order. The CLI does not send acknowledgements — the resulting events appear in the output stream.

### Terminal output

Regardless of socket connections, the CLI always prints human-readable output to its own stdout. This is the terminal view. It is independent of the socket — the two outputs are parallel, not modes.

---

## Module Layout

```
quack_norris/cli/
├── __init__.py
├── __main__.py       ← arg parsing; dispatches interactive vs non-interactive
├── session.py        ← session selection menu; new session creation
├── renderer.py       ← print events to stdout (human-readable)
├── approval.py       ← approval card + pattern picker (interactive only)
└── socket_server.py  ← TCP socket server; replay + live stream; receive commands
```

---

Last Updated: 2026-07-09
