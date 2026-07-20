"""Rich user input for the interactive REPL.

Handles three concerns in one blocking call (``read_user_input``):

1. **Multi-line continuation** — a line ending in ``\\`` continues onto the
   next line (``... `` prompt), backslash stripped, lines joined with ``\\n``.

2. **Bulk paste detection** — if ≥ 2 lines arrive faster than
   ``PASTE_WINDOW_MS`` (default 20 ms, override via ``QUACK_PASTE_WINDOW_MS``
   env var) they are treated as a single paste event and echoed as
   ``[pasted N lines]`` so the terminal stays readable.  The **full text is
   still sent to the LLM unchanged**.

3. **Image path detection** (stub for Part 3) — a single-line input whose
   stripped value resolves to an existing image file on disk is promoted to
   ``kind="image"``.  The image payload is populated by Part 3; for now only
   the kind is set so the display echo can be wired up in advance.

Cross-platform paste detection
-------------------------------
* **Windows** — uses ``msvcrt.kbhit()`` + ``msvcrt.getwch()`` to read the
  stdin buffer character by character without blocking.  After the first
  newline a tight ``time.perf_counter()`` loop polls for more characters for
  ``PASTE_WINDOW_MS`` milliseconds.
* **POSIX** — uses ``select.select([sys.stdin], [], [], timeout)`` on the raw
  stdin fd to check whether more input is available within the window.

If paste detection cannot be initialised (e.g. stdin is not a tty, or we are
in a test environment) the module falls back silently to plain ``input()``.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PASTE_WINDOW_MS: int = int(os.environ.get("QUACK_PASTE_WINDOW_MS", "80"))

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class ImageData:
    """Payload for an image input (populated in Part 3)."""

    mime_type: str           # e.g. "image/png"
    base64_data: str         # raw base64, no data-URI prefix
    source: str              # file path, "clipboard", etc.
    width: int | None = None
    height: int | None = None


@dataclass
class UserInput:
    """The result of one ``read_user_input()`` call.

    Attributes
    ----------
    kind:
        ``"text"``  — ordinary single- or multi-line (continuation) entry.
        ``"paste"`` — bulk paste of ≥ 2 lines detected.
        ``"image"`` — input resolved to an image file on disk.
    text:
        The full text to send to the LLM.  Always populated.
        For ``"image"`` this is a short human-readable label; the actual
        binary data lives in ``image_data``.
    raw_lines:
        The raw lines as captured from stdin (before joining).
    image_data:
        Populated only when ``kind == "image"``.
    """

    kind: Literal["text", "paste", "image"]
    text: str
    raw_lines: list[str] = field(default_factory=list)
    image_data: ImageData | None = None


# ---------------------------------------------------------------------------
# Platform-specific character reader
# ---------------------------------------------------------------------------

def _is_tty() -> bool:
    return hasattr(sys.stdin, "fileno") and sys.stdin.isatty()


if sys.platform == "win32":
    import msvcrt  # type: ignore[import]

    def _chars_available() -> bool:
        """Return True if at least one character is waiting in the stdin buffer."""
        return msvcrt.kbhit()  # type: ignore[attr-defined]

    def _read_char() -> str:
        """Read exactly one character from stdin (blocking)."""
        ch = msvcrt.getwch()  # type: ignore[attr-defined]
        # getwch returns a 2-char string for special keys — ignore them
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()  # discard the second byte  # type: ignore[attr-defined]
            return ""
        # On Windows, pasted emojis can arrive as lone surrogate halves which
        # crash sys.stdout.write (UTF-8 codec, surrogates not allowed).
        # Round-trip through UTF-8 to replace any lone surrogates with U+FFFD.
        ch = ch.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        return ch

    def _read_line_with_paste_detection(prompt: str) -> tuple[str, bool]:
        """Print *prompt*, read chars until newline, detect if a paste follows.

        Returns ``(line_text, more_data_pending)`` where ``more_data_pending``
        is True when more input arrived within ``PASTE_WINDOW_MS`` after the
        newline — signalling that this is a bulk paste.
        """
        sys.stdout.write(prompt)
        sys.stdout.flush()

        buf: list[str] = []
        while True:
            ch = _read_char()
            if ch == "\r" or ch == "\n":
                # Echo newline (getwch does not do this automatically)
                sys.stdout.write("\n")
                sys.stdout.flush()
                break
            if ch == "\x08":  # backspace
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if ch == "\x03":  # Ctrl+C
                raise KeyboardInterrupt
            if ch == "\x04":  # Ctrl+D / EOF
                raise EOFError
            if ch:
                buf.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()

        line = "".join(buf)

        # Poll for more data for PASTE_WINDOW_MS
        deadline = time.perf_counter() + PASTE_WINDOW_MS / 1000.0
        while time.perf_counter() < deadline:
            if _chars_available():
                return line, True
            time.sleep(0.001)
        return line, False

else:
    import select  # type: ignore[import]

    def _read_line_with_paste_detection(prompt: str) -> tuple[str, bool]:
        """POSIX variant — use select() to detect more data after the newline."""
        line = input(prompt)

        # Check whether more data is waiting on stdin
        ready, _, _ = select.select([sys.stdin], [], [], PASTE_WINDOW_MS / 1000.0)
        return line, bool(ready)


# ---------------------------------------------------------------------------
# Core reader
# ---------------------------------------------------------------------------

def _drain_paste_lines() -> list[str]:
    """Drain remaining lines from a paste — keep reading until silence."""
    lines: list[str] = []
    if sys.platform == "win32":
        # Read char-by-char until PASTE_WINDOW_MS of silence
        buf: list[str] = []
        deadline = time.perf_counter() + PASTE_WINDOW_MS / 1000.0
        while True:
            if _chars_available():
                ch = _read_char()
                deadline = time.perf_counter() + PASTE_WINDOW_MS / 1000.0
                if ch == "\r" or ch == "\n":
                    lines.append("".join(buf))
                    buf = []
                elif ch == "\x03":
                    raise KeyboardInterrupt
                elif ch == "\x04":
                    break
                elif ch:
                    buf.append(ch)
            elif time.perf_counter() > deadline:
                if buf:
                    lines.append("".join(buf))
                break
            else:
                time.sleep(0.001)
    else:
        import select  # noqa: PLC0415
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], PASTE_WINDOW_MS / 1000.0)
            if not ready:
                break
            line = sys.stdin.readline()
            if not line:
                break
            lines.append(line.rstrip("\n").rstrip("\r"))
    return lines


def _try_image_path(text: str) -> ImageData | None:
    """If *text* is a path to an existing image file, return a stub ImageData."""
    stripped = text.strip()
    # Strip surrounding quotes (common when drag-dropping on Windows)
    if len(stripped) >= 2 and stripped[0] in ('"', "'") and stripped[-1] == stripped[0]:
        stripped = stripped[1:-1]
    p = Path(stripped)
    if p.suffix.lower() in _IMAGE_SUFFIXES and p.exists():
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return ImageData(
            mime_type=mime_map.get(p.suffix.lower(), "image/png"),
            base64_data="",   # populated in Part 3
            source=str(p.resolve()),
        )
    return None


def _read_user_input_tty() -> UserInput:
    """Full paste-detecting reader — used when stdin is a real TTY."""
    lines: list[str] = []
    prompt = "> "

    first_line, more_pending = _read_line_with_paste_detection(prompt)

    if more_pending:
        # Bulk paste — drain, echo immediately, then offer "... " continuation
        rest = _drain_paste_lines()
        all_lines = [first_line, *rest]
        _echo_paste(len(all_lines))
        try:
            extra = input("... ")
        except (EOFError, KeyboardInterrupt):
            extra = ""
        if extra:
            all_lines.append(extra)
        text = "\n".join(all_lines)
        return UserInput(kind="paste", text=text, raw_lines=all_lines)

    # --- Single line (or start of \ continuation) ---
    # Continuation lines also go through paste detection so that pasting
    # after a "\" works correctly — the pasted lines get drained and appended.
    line = first_line
    while line.endswith("\\"):
        lines.append(line[:-1])
        try:
            line, more_pending = _read_line_with_paste_detection("... ")
        except EOFError:
            line = ""
            more_pending = False
            break
        if more_pending:
            # Paste detected mid-continuation — drain, echo, then offer "... "
            rest = _drain_paste_lines()
            lines.extend([line, *rest])
            _echo_paste(len(lines))
            try:
                extra = input("... ")
            except (EOFError, KeyboardInterrupt):
                extra = ""
            if extra:
                lines.append(extra)
            return UserInput(kind="paste", text="\n".join(lines), raw_lines=lines)
    lines.append(line)

    text = "\n".join(lines)

    # Image path detection (stub — base64_data filled in Part 3)
    if len(lines) == 1:
        img = _try_image_path(text)
        if img is not None:
            label = Path(img.source).name
            return UserInput(kind="image", text=text, raw_lines=lines, image_data=img)

    return UserInput(kind="text", text=text, raw_lines=lines)


def _read_user_input_fallback() -> UserInput:
    """Fallback for non-TTY stdin (pipes, tests) — plain input() with continuation.

    A line ending in ``\\`` continues onto the next line; the backslash is
    stripped and the lines are joined with ``\\n``.

    Continuation rules:
    - Line ending with ``\\`` → strip backslash, read next line with ``... ``
    - Empty line **while in continuation** → preserved as blank line, keep reading
    - Any other line while in continuation → appended as final line, stop
    - Any line (including empty) when NOT in continuation → stop immediately
    """
    lines: list[str] = []
    prompt = "> "
    in_continuation = False
    while True:
        line = input(prompt)
        if line.endswith("\\"):
            lines.append(line[:-1])  # strip trailing backslash, keep reading
            prompt = "... "
            in_continuation = True
        elif in_continuation and line == "":
            # Blank line mid-continuation → insert blank line and keep reading
            lines.append("")
        else:
            lines.append(line)
            break
    text = "\n".join(lines)
    return UserInput(kind="text", text=text, raw_lines=lines)


def read_user_input() -> UserInput:
    """Blocking call — read one logical user message from stdin.

    Uses paste detection when stdin is a real TTY; falls back to plain
    ``input()`` otherwise (pipes, test harnesses, CI).
    """
    if _is_tty():
        return _read_user_input_tty()
    return _read_user_input_fallback()


def read_single_line(prompt: str) -> str:
    """Read exactly one line from stdin — no paste detection, no continuation.

    Use this for approval prompts and other single-answer inputs so they never
    conflict with the msvcrt-based paste reader on Windows.  On a real TTY on
    Windows this uses the same ``_read_line_with_paste_detection`` path (which
    owns the msvcrt buffer) but ignores the ``more_pending`` flag; on POSIX and
    non-TTY it falls back to plain ``input()``.
    """
    if _is_tty() and sys.platform == "win32":
        line, _ = _read_line_with_paste_detection(prompt)
        return line
    return input(prompt)


# ---------------------------------------------------------------------------
# Echo helper (called from __main__.py after read_user_input returns)
# ---------------------------------------------------------------------------

def _echo_paste(n: int) -> None:
    """Print the paste echo immediately — called inline during TTY read."""
    print(f"  [pasted {n} line{'s' if n != 1 else ''}]")


def echo_input(ui: UserInput) -> None:
    """Print a compact summary line for paste / image inputs.

    Paste echoes are printed inline during reading (via ``_echo_paste``), so
    this function only handles image echoes.
    """
    if ui.kind == "image" and ui.image_data is not None:
        img = ui.image_data
        name = Path(img.source).name
        dims = f"  {img.width}×{img.height}" if img.width and img.height else ""
        ext = Path(img.source).suffix.lstrip(".").upper()
        print(f"  [image: {name}{dims}  {ext}]")
