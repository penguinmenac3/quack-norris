# Web UI Server

## Overview

The Web UI server is a small HTTP server with no agent logic. It:
- Lists sessions by scanning `meta.json` files
- Serves session events as SSE (by relaying the CLI socket, or reading the session file for cold sessions)
- Forwards user commands to the CLI socket (spawning the CLI process if needed)
- Emits a global session-status SSE stream for the sidebar

It is started with `quack-norris webui` and serves the PWA frontend at the same address.

---

## API

```
GET  /sessions                        list sessions (unarchived)
GET  /sessions?include_archived=true  include archived sessions

GET  /events                          SSE: session status changes (sidebar feed)

GET  /chat/<id>                       SSE: event stream for one session
POST /chat/<id>                       send command to session
POST /chat/<id>/archive               archive session
```

---

## `GET /sessions`

Scans `~/.quack-norris/sessions/*/meta.json` and returns a JSON array. Sorted by `last_active` descending. Unlike the CLI here is no limit on the number of sessions returned.

```json
[
  {
    "id": "a3f5e8b2-...",
    "name": "Auth refactor",
    "agent": "my-app/Backend Developer",
    "status": "idle",
    "last_active": "2026-07-09T16:30:01Z",
    "is_hot": true
  },
  ...
]
```

`is_hot` is derived by checking if the PID in `meta.json` is alive and the port is reachable. It is not stored — computed on each request.

With `?include_archived=true`, also scans `sessions/archived/*/meta.json` and appends those entries with `"archived": true`.

---

## `GET /events`

A persistent SSE stream. The browser opens this once for the lifetime of the tab. It receives session-level status updates that drive the sidebar.

```
event: session_status
data: {"id": "a3f5e8b2-...", "status": "working", "is_hot": true}

event: session_status
data: {"id": "a3f5e8b2-...", "status": "blocked", "is_hot": true}

event: session_status
data: {"id": "a3f5e8b2-...", "status": "idle", "is_hot": true}
```

The server emits on this stream whenever:
- A CLI socket connection opens or closes (hot/cold transition)
- A `content_start`, `content_end`, `tool_call_start`, `tool_call_result`, or `error` event is seen on any active socket

The stream is push-only. The browser does not send on this connection.

---

## `GET /chat/<id>`

Returns an SSE stream of all events for the session. Used when the user opens a session in the Web UI.

### If CLI process is alive (socket reachable)

1. Connect to CLI socket (`127.0.0.1:<port>` from `meta.json`)
2. CLI replays full `session.jsonl` over the socket, then streams live events
3. Server relays all events to the SSE client as they arrive
4. Each event is sent as:

```
id: 42
event: content_end
data: {"id":42,"type":"content_end","ts":"...","data":{"message_id":"m_002","text":"Hello!"}}
```

The SSE `id:` field matches the event's `id` field. This enables standard SSE reconnection via `Last-Event-ID`.

**Reconnect with Last-Event-ID**: Browser sends `Last-Event-ID: 47` on reconnect. The server relays this to the CLI by connecting to the socket as normal (CLI always replays from 0). The server skips events with `id ≤ 47` before forwarding to the SSE client. No events are lost.

### If CLI process is dead (no socket)

1. Read `session.jsonl` directly
2. Stream each non-blank line as an SSE event
3. Close the SSE stream when the file is exhausted (no live tail)

The browser receives a complete history. When the SSE stream closes (server-initiated), the browser knows the session is cold. It will attempt to reconnect — the server responds immediately with the same static history. After two failed reconnect attempts, the browser stops and shows the session as cold.

To prevent infinite reconnect loops, the server sends a synthetic event before closing a cold-session stream:

```
event: session_cold
data: {"id": "a3f5e8b2-..."}
```

The browser handles `session_cold` by cancelling the SSE reconnect and marking the session as cold in the UI.

---

## `POST /chat/<id>`

Sends a command to the session. The request body is a command object (see [03-event-format.md](03-event-format.md)):

```json
{"type": "cmd_user_message", "data": {"message_id": "m_007", "text": "Refactor login.py", "config": null}}
```

### If CLI process is alive

Forward the command JSON to the CLI socket. Return `202 Accepted` immediately. The resulting events will appear on the `GET /chat/<id>` SSE stream.

### If CLI process is dead and command is `cmd_user_message`

1. Create session directory if it does not exist (new session)
2. Spawn: `quack-norris chat --resume <id>` (detached, no terminal, `owner: webui`)
3. Wait for the CLI process to write `meta.json` with its port (poll with short timeout)
4. Connect to the socket
5. Forward the command
6. Return `202 Accepted`

Any connected `GET /chat/<id>` SSE client will automatically receive the replay + new events from the socket.

### If CLI process is dead and command is not `cmd_user_message`

Return `409 Conflict`. Approvals and stops are only meaningful while a process is running.

### If session is `terminal`-owned and process is alive

Return `409 Conflict` with body:

```json
{"error": "session_locked", "message": "Session is owned by a terminal process (PID 12345). Close the terminal first."}
```

---

## `POST /chat/<id>/archive`

Archives the session.

1. If CLI process is alive and `owner: webui`: send `cmd_agent_stop` to socket, wait for clean exit (up to 5s), then force-kill
2. If CLI process is alive and `owner: terminal`: return `409 Conflict` — user must close the terminal
3. Move `sessions/<id>/` to `sessions/archived/<id>/`
4. Emit `{"id": "<id>", "archived": true}` on `GET /events` stream
5. Return `200 OK`

---

## Process Management

### Spawning

```python
process = await asyncio.create_subprocess_exec(
    "quack-norris", "chat", "--resume", session_id,
    stdin=asyncio.subprocess.DEVNULL,
    stdout=asyncio.subprocess.DEVNULL,
    stderr=asyncio.subprocess.DEVNULL,
)
```

The process is fully detached — no stdin/stdout/stderr from the server's perspective. It runs independently. The server connects to it via socket.

### Idle timeout (webui-owned sessions)

A background task runs every 5 minutes. For each `owner: webui` session with a live process and `status: idle`:
- If `last_active` is more than 30 minutes ago: send `cmd_agent_stop`, wait for exit, update `meta.json`

Terminal-owned sessions are never touched by this task.

### Auto-purge (archived sessions)

At server startup and once per hour: scan `sessions/archived/*/meta.json`. If `last_active` is more than 30 days ago, delete the directory.

---

## Session Hot/Cold in the UI

The browser derives session temperature from SSE connection state:

| Signal | Meaning |
|--------|---------|
| `GET /chat/<id>` SSE stays open | Session is hot (CLI process alive) |
| `session_cold` event received | Session is cold (no process) |
| `GET /events` emits `is_hot: true` | Session is hot (for sidebar, regardless of which session is open) |

For the currently focused session, the UI shows:
- **Hot idle** — SSE open, last event `content_end` → `> ` prompt appears instantly on send
- **Cold idle** — SSE closed → `Starting...` shown briefly when user sends a message

For sidebar sessions (not focused), `GET /events` provides hot/cold status without needing per-session SSE connections.

---

## Module Layout

```
quack_norris/webui/
├── __init__.py
├── __main__.py       ← entry point for `quack-norris webui`
├── server.py         ← FastAPI app factory + startup
├── sessions.py       ← scan meta.json files; list/archive/purge
├── relay.py          ← socket → SSE relay; GET /chat/<id> handler
├── commands.py       ← POST /chat/<id>; spawn logic
└── events.py         ← GET /events broadcaster
```

---

## Frontend Serving

The FastAPI server mounts the built PWA at `/`:

```python
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
```

All API routes are under `/sessions`, `/events`, `/chat`. There is no path conflict with the PWA.

---

Last Updated: 2026-07-09
