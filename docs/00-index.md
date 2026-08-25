# Quack Norris Documentation

Quack Norris is a stateless SLM-oriented agent core with native tools, agent/skill discovery, and an ACP server.

## Documents

1. [Architecture](01-architecture.md)
2. [Core](02-core.md)
3. [Tools](03-tools.md)
4. [Skills and agents](04-skills-and-agents.md)
5. [ACP](05-acp.md)

## Entry points

| Command | Purpose |
|---|---|
| `quack-norris acp [--config FILE]` | Start the ACP stdio server |
| `quack-norris-manage ...` | Install and manage agents and skills |
| `quack-norris-sandbox ...` | Create isolated worktrees/containers |

The project does not include an interactive chat client or Web UI. Use an ACP-compatible client to interact with the ACP server.

Deferred interoperability and UX work is tracked in [TODO.md](../TODO.md).
