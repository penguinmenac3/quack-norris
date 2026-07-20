# Architecture

## Design Philosophy

QuackNorris is **CLI-first**. The agent runs as a CLI process. The Web UI is a separate application that starts, stops, and observes CLI processes — it contains no agent logic of its own.

### Key Principles

1. **CLI process = agent** — one process per session, owns the agent loop, the session file, and the socket
2. **Session file = source of truth** — all events are appended to a `.jsonl` file; nothing is in a database
3. **Web UI = thin relay** — scans files, spawns processes, proxies a TCP socket to SSE; no agent knowledge
4. **No simultaneous CLI + Web UI on the same session** — one owner at a time; the Web UI can take over from a dead CLI process
5. **Terminal closes → agent dies** — clean, predictable; the Web UI can restart the agent if needed

---

## Components

```
┌──────────────────────────────────────────────────────┐
│  User's machine                                      │
│                                                      │
│  ┌─────────────┐      ┌───────────────────────────┐  │
│  │  Terminal   │      │   Browser (PWA)           │  │
│  │             │      │                           │  │
│  │  quack-     │      │  GET /sessions            │  │
│  │  norris     │      │  GET /events   (SSE)      │  │
│  │  chat       │      │  GET /chat/<id> (SSE)     │  │
│  └──────┬──────┘      │  POST /chat/<id>          │  │
│         │ stdout      └──────────┬────────────────┘  │
│         │ (text)                 │ HTTP              │
│         │                        ▼                   │
│         │             ┌───────────────────────────┐  │
│         │             │   Web UI Server           │  │
│         │             │   (quack-norris webui)    │  │
│         │             │                           │  │
│         │             │  • scans session files    │  │
│         │             │  • spawns CLI processes   │  │
│         │             │  • proxies TCP socket     │  │
│         │             └──────────┬────────────────┘  │
│         │                        │ TCP 127.0.0.1     │
│         │                        │ (JSON events)     │
│         ▼                        ▼                   │
│  ┌────────────────────────────────────────────────┐  │
│  │   CLI Process  (quack-norris chat)             │  │
│  │                                                │  │
│  │  • runs agent loop                             │  │
│  │  • writes events to session.jsonl              │  │
│  │  • streams text to stdout (human-readable)     │  │
│  │  • serves JSON events on TCP socket            │  │
│  │  • receives commands on TCP socket             │  │
│  └────────────────────────────────────────────────┘  │
│         │                                            │
│         ▼                                            │
│  ~/.quack-norris/sessions/<id>/                      │
│    session.jsonl   ← append-only event log           │
│    meta.json       ← fast index (pid, port, status)  │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### CLI Process

The CLI process is the agent. It:
- Runs the agent loop (LLM calls, tool execution, approval gating)
- Appends every event to `session.jsonl`
- Prints human-readable output to stdout
- Listens on a TCP port (`127.0.0.1:<port>`) for socket clients
- On each new socket connection: replays full `session.jsonl` as JSON events, then streams live events
- Receives commands (user messages, approvals, stop) on the same socket

### Web UI Server

A small HTTP server with no agent knowledge. It:
- Scans `~/.quack-norris/sessions/` for `meta.json` files to list sessions
- Serves `GET /events` as a global SSE stream of session status changes
- Serves `GET /chat/<id>` as an SSE stream by connecting to the CLI socket (or serving static file history if no process is running)
- Forwards `POST /chat/<id>` commands to the CLI socket, spawning the CLI process first if needed

### Session Files

Everything persists in `~/.quack-norris/sessions/<id>/`. See [02-session-storage.md](02-session-storage.md).

---

## Data Flow

### User sends a message (CLI)

```
User types at > prompt
  → CLI reads from stdin
  → CLI publishes user_message to session.jsonl
  → CLI forwards event to any connected socket clients
  → CLI runs agent loop
  → Agent streams content_delta events → appended to jsonl + sent to socket + printed to stdout
  → Agent finishes → content_end appended → socket clients see idle state
```

### User sends a message (Web UI, process alive)

```
User clicks Send in browser
  → POST /chat/<id>  {"type": "user_message", "text": "..."}
  → Web UI server forwards to CLI socket
  → CLI receives command, runs agent loop
  → Agent events → appended to jsonl + streamed to Web UI server via socket
  → Web UI server forwards events to browser via GET /chat/<id> SSE
  → Browser renders in real time
```

### User sends a message (Web UI, process dead)

```
User clicks Send in browser
  → POST /chat/<id>
  → Web UI server checks meta.json → pid dead, no socket
  → Web UI server spawns: quack-norris chat --resume <id>  (detached, no terminal)
  → CLI process starts, replays history from jsonl on new socket connection
  → Web UI server connects to socket, relays events to SSE
  → Browser shows "Starting..." briefly, then events flow normally
```

### User reads a session (no message sent)

```
User clicks session in sidebar
  → GET /chat/<id>
  → Web UI server checks meta.json → pid alive, socket reachable
       → connect to socket, relay full replay + live events to SSE
  → Web UI server checks meta.json → pid dead
       → read session.jsonl directly, stream as static SSE, close
  → Browser renders history
  → No CLI process spawned (read is free)
```

---

## Session Ownership

Only one client owns a session at a time:

| Scenario | Owner | Web UI behaviour |
|----------|-------|-----------------|
| User opened `quack-norris chat` in terminal | `terminal` (written in meta.json) | Shows session as active; POST /chat returns 409 Conflict |
| Web UI spawned the process | `webui` | Full control; 30-min idle timeout applies |
| No process running | none | Reads static history; spawns on first POST |

`terminal`-owned sessions cannot be taken over by the Web UI while the process is alive. The Web UI shows a "locked by terminal" indicator. The user must close the terminal first (or explicitly stop it), after which the Web UI can resume.

---

## Deployment

### Local (default)

```
quack-norris webui        # starts the Web UI server on http://127.0.0.1:8765
quack-norris chat         # start/resume a session in the terminal
```

Both commands are optional and independent. The CLI works without the Web UI. The Web UI works without any terminal sessions open.

### Remote

The Web UI server can be exposed remotely (HTTPS + API key). The CLI always runs locally on the machine where the agent operates. Remote access is for the Web UI only.

---

## Technology Stack

### CLI + Agent
- **Language**: Python 3.14+
- **Async**: asyncio (agent loop, socket server)
- **LLM**: httpx (streaming, OpenAI-compatible)
- **Storage**: append-only `.jsonl` files + `meta.json`
- **IPC**: TCP socket on `127.0.0.1:<ephemeral-port>`

### Web UI Server
- **Language**: Python 3.14+
- **Framework**: FastAPI (4 endpoints + SSE)
- **Process management**: `asyncio.create_subprocess_exec`
- **No agent dependencies** — only stdlib + FastAPI + httpx

### Web UI Frontend
- **Language**: TypeScript (strict)
- **Framework**: None — custom TypeScript + in-house `webui` component library
- **Build**: Vite
- **Zero runtime npm dependencies** outside `webui`

---

Last Updated: 2026-07-09
