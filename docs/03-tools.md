# Tools

## Native tools

`quack_norris.tools` contains tools for direct SDK hosts:

| Tool | Purpose |
|---|---|
| `file_view` | Read files or list directories |
| `file_write` | Create files without silently overwriting existing files |
| `file_str_replace` | Replace one exact occurrence |
| `file_move` | Move a file or directory |
| `file_delete` | Delete a file or directory |
| `bash` / `pwsh` | Run a platform shell command |
| `check_tool` | Poll a managed background operation |
| `await_tool` | Wait for a managed operation |
| `kill_tool` | Cancel a managed operation |

File-tool factories receive the current workspace and an optional auto-approved scratch root. They do not depend on ACP or session storage.

For normal SDK use, `make_native_tools(workspace, skills=bool(skills))` creates file, platform shell, and operation tools, plus `use_skill` when requested. Skill discovery remains caller-owned.

## Explicit operation tools

Operation tools are injected explicitly:

```python
registry = ProcessRegistry()
tools = [
    make_shell_tool(get_cwd, registry),
    *make_operation_tools(registry),
]
```

The core never adds poll/await/kill automatically. Hosts may omit or replace them. Native and ACP terminal commands are awaited for up to 30 seconds: commands that finish within the window return output directly and release the process/terminal, while only slower commands return an operation handle. The result returns immediately when the command exits; it does not always wait 30 seconds.

## ACP tools

ACP sessions assemble equivalent model-facing tools from client capabilities:

| Capability | ACP callback |
|---|---|
| Read | `read_text_file` |
| Write | `write_text_file` |
| `pwsh` on Windows / `bash` elsewhere | `create_terminal` |
| Poll | `terminal_output` |
| Await | `wait_for_terminal_exit` |
| Cancel | `kill_terminal` and `release_terminal` |
| Move/delete | Platform command through `create_terminal` |
| Permission | `request_permission` |

Tools are omitted when the client does not advertise the required capability.

## Path safety

Both implementations resolve relative paths against the session/workspace root and reject paths outside allowed roots. ACP sends normalized absolute paths to client callbacks.

## Exact replacement limitation

ACP has no atomic compare-and-swap filesystem operation. `file_str_replace` reads, validates uniqueness, reads again, and writes the replacement, but an external edit can still race the final write.
