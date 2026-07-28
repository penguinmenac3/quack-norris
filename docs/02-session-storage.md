# Session Storage

## Overview

Every session is a directory under `~/.quack-norris/sessions/<id>/`. The directory is created when the first message is sent. There is no database.

---

## Directory Layout

```
~/.quack-norris/
  sessions/
    <id>/
      session.jsonl     ← append-only event log (source of truth)
      meta.json         ← fast index: pid, port, status, name, last_active
      snapshots/        ← (future) filesystem snapshots for undo
      attachments/      ← (future) files dragged into the chat
    archived/
      <id>/
        session.jsonl
        meta.json
```

Session IDs are UUIDs (e.g. `a3f5e8b2-1c4d-4e9f-b7a6-2d8c3f1e0a5b`). They are generated client-side (Web UI) or by the CLI on new session creation.

---

## `session.jsonl`

An append-only file of newline-delimited JSON objects. Each line is one event. Lines are never modified or deleted — this is a pure append log.

### Event line format

```json
{"id": 42, "type": "content_end", "ts": "2026-07-09T16:30:01Z", "data": {"message_id": "m_002", "text": "Hello! How can I help?"}}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Monotonically increasing, unique within the session. Line number (0-indexed). |
| `type` | string | Event type. See [03-event-format.md](03-event-format.md). |
| `ts` | string | ISO 8601 timestamp. |
| `data` | object | Event-specific payload. Schema varies by type. |

### Ordering guarantee

Events are written in order. The `id` field equals the 0-based line number. Readers can use line position as the event ID — no parsing needed to seek to a specific event.

### Content only — no session config in the log

`session.jsonl` contains only conversation events: user messages, agent responses, tool calls, system hints, checkpoints, and errors. Session config (name, agent, model, cwd) is stored exclusively in `meta.json` and never appears in the log.

The first line of the log is the first `user_message` event.

---

## `meta.json`

A small JSON file updated by the CLI process after each significant state change. Used by the Web UI server for fast session listing without reading the full `session.jsonl`.

```json
{
  "id": "a3f5e8b2-1c4d-4e9f-b7a6-2d8c3f1e0a5b",
  "name": "Auth refactor",
  "agent": "my-app/Backend Developer",
  "model": null,
  "cwd": "/home/alice/my-app",
  "status": "idle",
  "pid": 12345,
  "port": 54321,
  "owner": "terminal",
  "created_at": "2026-07-09T16:00:00Z",
  "last_active": "2026-07-09T16:30:01Z"
}
```

| Field | Description |
|-------|-------------|
| `id` | Session UUID |
| `name` | Display name (null if unnamed) |
| `agent` | Current agent name |
| `model` | Current model override (null = agent default) |
| `cwd` | Project working directory |
| `status` | `idle`, `working`, `blocked`, `error` |
| `pid` | PID of the running CLI process (null if no process) |
| `port` | TCP port the CLI socket is listening on (null if no process) |
| `owner` | `"terminal"`, `"webui"`, or `null` |
| `created_at` | ISO 8601, from `session_created` event |
| `last_active` | ISO 8601, updated on each event write |

`meta.json` is **not** the source of truth — it is a denormalised cache. If `meta.json` is stale or missing, it can be reconstructed by reading `session.jsonl`.

### Staleness handling

The Web UI server checks PID liveness before trusting `pid` and `port`. If the PID is dead, it treats the session as cold regardless of what `meta.json` says, and clears `pid`, `port`, `owner` in memory (but does not rewrite `meta.json` — only the CLI process writes it).

---

## Status Derivation

Session status is derived from the event stream. The CLI process derives it in real time and writes it to `meta.json`. The Web UI derives it from the last event seen on the socket (or from the last event in `session.jsonl` for cold sessions).

| Status | Condition |
|--------|-----------|
| `idle` | Last event is `content_end` with no subsequent `tool_call_start` pending |
| `working` | `content_start` without `content_end`, or `tool_call_start` without `tool_call_result` |
| `blocked` | `tool_call_start` with `needs_approval: true` and no `tool_call_approved`/`tool_call_denied` yet |
| `error` | Last event is `error` |

---

## Archive

Archiving moves the session directory to `sessions/archived/<id>/`:

```
sessions/a3f5e8b2.../   →   sessions/archived/a3f5e8b2.../
```

Archived sessions:
- Do not appear in `GET /sessions` by default
- Appear in `GET /sessions?include_archived=true`
- Are auto-purged 30 days after `last_active` (checked at Web UI server startup and periodically)
- Can be manually restored by moving the directory back to `sessions/`

The Web UI server never hard-deletes session files — it only moves them. Purging (after 30 days) is the only actual deletion.

---

## Session Lifecycle

```
First POST /chat/<new-id>
  → CLI creates sessions/<id>/
  → writes session.jsonl (session_created event)
  → writes meta.json
  → runs agent loop

Session active
  → events appended to session.jsonl
  → meta.json updated after each event

Terminal closed / process killed
  → session.jsonl intact
  → meta.json has stale pid/port (ignored by Web UI server)
  → session is cold, readable from file

POST /chat/<id> again (Web UI or new terminal)
  → new CLI process spawned or user runs chat --resume <id>
  → reads full session.jsonl for history
  → appends new events
  → writes new meta.json with fresh pid/port

POST /chat/<id>/archive
  → CLI process stopped (if webui-owned)
  → directory moved to sessions/archived/<id>/

Auto-purge (30 days after last_active)
  → directory deleted
```

---

## Config Changes Mid-Session

Slash commands (`/agent`, `/model`, `/project`) apply immediately:

1. CLI updates its in-memory config
2. If the session directory already exists: `meta.json` is rewritten immediately
3. If the session has not been created yet (no user message sent): config is held in memory only — no files are written, no empty session is created
4. A `system_hint` event is appended to `session.jsonl` (if the session exists) so the agent is aware of the change in its LLM context

The hint is inserted into the LLM context as a system-role message — the agent sees it but is not prompted to respond to it.

---

Last Updated: 2026-07-09
