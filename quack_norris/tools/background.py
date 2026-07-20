"""Background process registry.

When a shell command is still running after its timeout, it is promoted to
a background process rather than killed.  The ``ProcessRegistry`` tracks all
live (and recently-finished) background processes keyed by short handles
such as ``bg-3f2a``.

Each ``RunningProcess`` drains stdout continuously into a deque so
``check_tool`` always has fresh output without needing to block.
"""

from __future__ import annotations

import asyncio
import os
import random
import string
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# RunningProcess — one tracked background process
# ---------------------------------------------------------------------------

@dataclass
class RunningProcess:
    """A shell process promoted to a background handle.

    Parameters
    ----------
    handle:
        Short identifier, e.g. ``bg-3f2a``.
    proc:
        The live ``asyncio.subprocess.Process`` object.
    command:
        The original shell command string (for display).
    started_at:
        UTC timestamp when the process was started.
    """

    handle: str
    proc: asyncio.subprocess.Process
    command: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # stdout lines drained continuously by _drain_task
    stdout_buffer: deque[str] = field(default_factory=deque)
    finished: bool = False
    exit_code: int | None = None

    # asyncio task that pumps stdout into the buffer
    _drain_task: asyncio.Task | None = field(default=None, repr=False)

    def start_draining(self) -> None:
        """Spawn the background task that reads stdout into the buffer."""
        self._drain_task = asyncio.create_task(
            self._drain_stdout(), name=f"drain-{self.handle}"
        )

    async def _drain_stdout(self) -> None:
        """Read stdout line-by-line until EOF, then mark process finished."""
        try:
            assert self.proc.stdout is not None  # always PIPE
            async for raw_line in self.proc.stdout:
                line = raw_line.decode(errors="replace").rstrip("\n")
                self.stdout_buffer.append(line)
        except Exception:  # noqa: BLE001
            pass
        finally:
            # Wait for the process to fully exit and capture the return code.
            try:
                await self.proc.wait()
            except Exception:  # noqa: BLE001
                pass
            self.exit_code = self.proc.returncode
            self.finished = True

    def buffered_output(self) -> str:
        """Return all buffered stdout lines joined as a string."""
        return "\n".join(self.stdout_buffer)

    def uptime_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()


# ---------------------------------------------------------------------------
# ProcessRegistry — session-scoped store
# ---------------------------------------------------------------------------

def _new_handle() -> str:
    """Generate a short random handle like ``bg-3f2a``."""
    chars = string.ascii_lowercase + string.digits
    suffix = "".join(random.choices(chars, k=4))
    return f"bg-{suffix}"


class ProcessRegistry:
    """Session-scoped registry of background processes.

    One instance is created per interactive/non-interactive session so
    parallel CLI sessions never share handles.
    """

    def __init__(self) -> None:
        self._procs: dict[str, RunningProcess] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        proc: asyncio.subprocess.Process,
        command: str,
    ) -> RunningProcess:
        """Promote *proc* to a tracked background process.

        Starts the stdout-drain task immediately and returns the
        ``RunningProcess`` with its freshly generated handle.
        """
        handle = self._unique_handle()
        rp = RunningProcess(handle=handle, proc=proc, command=command)
        self._procs[handle] = rp
        rp.start_draining()
        return rp

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, handle: str) -> RunningProcess | None:
        return self._procs.get(handle)

    def all_handles(self) -> list[str]:
        return list(self._procs.keys())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _unique_handle(self) -> str:
        for _ in range(16):
            h = _new_handle()
            if h not in self._procs:
                return h
        # Extremely unlikely collision fallback — use PID
        return f"bg-{os.getpid()}"
