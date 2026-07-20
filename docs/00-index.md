# QuackNorris 3.0 — Documentation

## Architecture

The system is **CLI-first**. The CLI process is the agent. The Web UI is a thin relay.

Read in this order:

1. **[01-architecture.md](01-architecture.md)** — overall design, components, data flow
2. **[02-session-storage.md](02-session-storage.md)** — session directory layout, event log, meta.json, archive
3. **[03-event-format.md](03-event-format.md)** — JSON event schemas (all event types)
4. **[04-cli.md](04-cli.md)** — CLI process: startup, REPL, approval flow, non-interactive mode, socket protocol
5. **[05-webui-server.md](05-webui-server.md)** — Web UI server: API endpoints, socket relay, process management
6. **[06-agent-system.md](06-agent-system.md)** — agent loop, tools, approval, context management

---

## Status

| Document | Status |
|----------|--------|
| 01-architecture.md | ✅ Complete |
| 02-session-storage.md | ✅ Complete |
| 03-event-format.md | ✅ Complete |
| 04-cli.md | ✅ Complete |
| 05-webui-server.md | ✅ Complete |
| 06-agent-system.md | ✅ Complete |

---

Last Updated: 2026-07-09
