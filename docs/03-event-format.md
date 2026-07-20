# Event Format

## Overview

Events are JSON objects. They appear in two places:
- **`session.jsonl`** — one event per line, appended by the CLI process
- **TCP socket** — streamed as newline-delimited JSON by the CLI process to connected clients (Web UI server, other tools)

The socket replays the full `session.jsonl` on each new connection, then continues with live events. Event IDs are monotonically increasing integers matching the line number in `session.jsonl`.

---

## Base Structure

```json
{"id": 42, "type": "content_end", "ts": "2026-07-09T16:30:01Z", "data": {...}}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | 0-based line number in `session.jsonl`. Unique and ordered within a session. |
| `type` | string | Event type (see below). |
| `ts` | string | ISO 8601 UTC timestamp. |
| `data` | object | Event-specific payload. |

---

## Session Events

Session config (name, agent, model, cwd) is stored exclusively in `meta.json`. It is never written to `session.jsonl`. The log is purely conversation content.

### `history_compacted`

Appended when history compaction runs (auto or manual). Events with `id ≤ cutoff_id` are excluded from the LLM context going forward. The raw events remain in the file permanently.

```json
{
  "id": 291,
  "type": "history_compacted",
  "ts": "2026-07-09T17:00:00Z",
  "data": {
    "cutoff_id": 289,
    "summary": "The user asked for a test run and a refactor of the auth module. Both completed successfully.",
    "trigger": "auto"
  }
}
```

| Field | Description |
|-------|-------------|
| `cutoff_id` | Events with `id ≤ cutoff_id` are replaced by `summary` in the LLM context |
| `summary` | LLM-generated summary of all history up to `cutoff_id` |
| `trigger` | `"auto"` (threshold exceeded) or `"manual"` (`/compact` or Web UI button) |

If multiple `history_compacted` events exist, only the one with the **highest `cutoff_id`** is used.

---

## Conversation Events

### `user_message`

User sent a message.

```json
{
  "id": 1,
  "type": "user_message",
  "ts": "2026-07-09T16:00:05Z",
  "data": {
    "message_id": "m_001",
    "text": "Can you check the tests?"
  }
}
```

---

### `system_hint`

A non-interactive log entry injected by the CLI when the user changes session config mid-conversation (`/agent`, `/model`, `/project`). Not sent to the agent as a prompt — it is inserted into the LLM context as a system-role message so the agent is aware of the change without being asked to respond.

```json
{
  "id": 7,
  "type": "system_hint",
  "ts": "2026-07-09T16:05:00Z",
  "data": {
    "text": "[System: Agent switched to my-app/Backend Developer]"
  }
}
```

Examples of generated hint text:
- `[System: Agent switched to my-app/Backend Developer]`
- `[System: Model switched to ollama/gemma3]`
- `[System: Project directory changed to /home/alice/other-app]`

Hints appear in the Web UI history as a subtle inline notice (not styled as a user or agent message). They are included in `history_compacted` summaries so context survives compaction.

---

### `content_start`

Agent begins generating a response.

```json
{
  "id": 2,
  "type": "content_start",
  "ts": "2026-07-09T16:00:06Z",
  "data": {"message_id": "m_002"}
}
```

### `content_delta`

Streaming chunk of agent response. Only written during live streaming; not present in `session.jsonl` after the turn completes (replaced by `content_end`).

```json
{
  "id": 3,
  "type": "content_delta",
  "ts": "2026-07-09T16:00:06Z",
  "data": {"message_id": "m_002", "text": "Sure, running them now"}
}
```

### `content_end`

Agent finished this response segment. Carries the complete text for replay. Replaces `content_start` + all `content_delta` entries in the log.

```json
{
  "id": 6,
  "type": "content_end",
  "ts": "2026-07-09T16:00:08Z",
  "data": {"message_id": "m_002", "text": "Sure, running them now..."}
}
```

**Log compaction**: When `content_end` is appended, the CLI process rewrites `session.jsonl` to remove the preceding `content_start` and `content_delta` lines for this `message_id`, replacing them with the `content_end` line at the correct position. IDs are preserved. This keeps the file from growing unboundedly during long streaming responses.

---

### `thinking_start` / `thinking_delta` / `thinking_end`

Same structure as content events, for models that expose chain-of-thought reasoning. Subject to the same compaction.

```json
{"id": 2, "type": "thinking_start", "ts": "...", "data": {"message_id": "m_002"}}
{"id": 3, "type": "thinking_delta", "ts": "...", "data": {"message_id": "m_002", "text": "I should check..."}}
{"id": 4, "type": "thinking_end",   "ts": "...", "data": {"message_id": "m_002", "text": "I should check the test output first."}}
```

---

### `tool_call_start`

Agent wants to execute a tool. Written when the tool call is about to be dispatched. If `needs_approval` is true, execution blocks until `tool_call_approved` or `tool_call_denied` is received.

```json
{
  "id": 7,
  "type": "tool_call_start",
  "ts": "2026-07-09T16:00:09Z",
  "data": {
    "call_id": "tc_001",
    "tool": "bash",
    "arguments": {"command": "uv run pytest"},
    "needs_approval": false,
    "approval_display": "uv run pytest",
    "suggested_patterns": ["uv run pytest", "uv run pytest *", "uv run *"]
  }
}
```

`approval_display` is a human-readable summary for the approval card. `suggested_patterns` is an AI-generated list of glob patterns for the pattern picker, from most specific to most permissive.

### `tool_call_approved`

User approved the tool call (interactive mode only).

```json
{
  "id": 8,
  "type": "tool_call_approved",
  "ts": "2026-07-09T16:00:10Z",
  "data": {
    "call_id": "tc_001",
    "pattern": "uv run *",
    "scope": "project"
  }
}
```

`pattern` and `scope` are present only if the user chose "Allow pattern". `scope` is `"session"`, `"project"`, or `"global"`. If the user chose "Allow once", both fields are omitted.

### `tool_call_denied`

User denied the tool call, or auto-denied in non-interactive mode.

```json
{
  "id": 8,
  "type": "tool_call_denied",
  "ts": "2026-07-09T16:00:10Z",
  "data": {
    "call_id": "tc_001",
    "auto": false
  }
}
```

`auto: true` when denied automatically (non-interactive mode).

### `tool_call_result`

Tool execution complete.

```json
{
  "id": 9,
  "type": "tool_call_result",
  "ts": "2026-07-09T16:00:12Z",
  "data": {
    "call_id": "tc_001",
    "tool": "bash",
    "was_approved": true,
    "result": "42 passed in 1.23s",
    "is_error": false
  }
}
```

**Log compaction**: No compaction for tool calls as they are different messages for the LLM for calling a tool and getting a response and there is no streaming.

---

### `error`

Unrecoverable error during agent execution.

```json
{
  "id": 10,
  "type": "error",
  "ts": "2026-07-09T16:00:15Z",
  "data": {
    "message": "LLM request failed: connection timeout",
    "code": "llm_timeout"
  }
}
```

---

## Commands (Socket Input Only)

These are not written to `session.jsonl` — they are commands sent **to** the CLI process over the socket by the Web UI server. The CLI receives them and takes the appropriate action (which then produces regular events in the log).

### `cmd_user_message`

Send a user message (with optional config delta).

```json
{
  "type": "cmd_user_message",
  "data": {
    "message_id": "m_005",
    "text": "Can you refactor login.py?",
    "config": {"name": "Login refactor", "agent": null, "model": null, "cwd": null}
  }
}
```

### `cmd_tool_call_approved`

```json
{
  "type": "cmd_tool_call_approved",
  "data": {"call_id": "tc_002", "pattern": null, "scope": null}
}
```

### `cmd_tool_call_denied`

```json
{
  "type": "cmd_tool_call_denied",
  "data": {"call_id": "tc_002"}
}
```

### `cmd_agent_stop`

```json
{
  "type": "cmd_agent_stop",
  "data": {}
}
```

### `cmd_compact`

Trigger a manual history compaction. Produced by the `/compact` slash command or the Web UI compact button.

```json
{
  "type": "cmd_compact",
  "data": {}
}
```

The CLI runs compaction immediately regardless of token count and appends a `history_compacted` event with `"trigger": "manual"`.

---

## Log Compaction

Compaction keeps `session.jsonl` from growing with redundant streaming events. It rewrites lines in-place (preserving IDs and line count) by replacing compacted events with a single summary event.

### What gets compacted

| Events removed | Replaced by |
|----------------|-------------|
| `content_start` + N×`content_delta` | `content_end` (at the position of `content_start`) |
| `thinking_start` + N×`thinking_delta` | `thinking_end` |

### What is never compacted

- `session_created` / `session_updated`
- `user_message`
- `tool_calls`
- `error`

### Mechanism

When `content_end` is written:
1. CLI scans backward in `session.jsonl` to find the matching `content_start` and all `content_delta` lines
2. Removes those lines
3. The `content_end` line is written at the end (note, that the ID can have gaps because we remove events)

---

Last Updated: 2026-07-09
