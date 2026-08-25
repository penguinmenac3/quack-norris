"""Stream-aware Markdown → ANSI terminal renderer.

Usage::

    r = MdStreamRenderer(stream=sys.stdout)
    for chunk in token_stream:
        r.feed(chunk)
    r.finish()

Design
------
Text arrives as arbitrary-length chunks (LLM tokens).  We process it
line-by-line:

* Characters are accumulated in a *line buffer*.
* Whenever a ``\\n`` is encountered in a chunk the completed line is
  rendered immediately, keeping the "live typing" feel.
* A trailing partial line (no ``\\n`` yet) is printed character-by-character
  as it arrives so the cursor advances in real time.
* ``finish()`` flushes any remaining partial line without a trailing newline.

Block-level rules (applied per completed line)
-----------------------------------------------
* ``# …`` / ``## …`` / ``### …``  — coloured + bold heading, rule afterwards
* ``---`` / ``===`` / ``***`` (≥3 repeated) — horizontal rule
* ``> …``  — blockquote with dim ``│`` gutter
* ``- …`` / ``* …`` / ``+ …`` (unordered list) — bullet ``•``
* ``1. …`` / ``2. …`` … (ordered list) — kept as-is, indented
* `` ``` `` (opening/closing) — toggles code-block mode

Inline rules (applied within a completed line, or to partial content)
----------------------------------------------------------------------
* ``**text**`` / ``__text__``  — bold
* ``*text*`` / ``_text_``      — italic (dim + italic)
* `` `text` ``                 — yellow inline code
* ``~~text~~``                 — strikethrough

Streaming inline handling
~~~~~~~~~~~~~~~~~~~~~~~~~
For partially arrived lines we cannot yet apply inline rules (we don't know
if the closing delimiter will arrive).  The partial line is printed raw but
with a *cursor rewind trick*: the partial content printed so far is tracked so
that when the line becomes complete, the cursor is rewound to the start of
that line and the fully-styled line is reprinted.

This works correctly on any ANSI terminal.  On non-tty streams (pipes) the
cursor escape is suppressed and text is simply printed twice briefly — callers
should use ``MdStreamRenderer`` only on tty output.
"""

from __future__ import annotations

import re
import sys
from typing import IO


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
ITALIC  = "\033[3m"
STRIKE  = "\033[9m"

FG_CYAN   = "\033[36m"
FG_BLUE   = "\033[34m"
FG_YELLOW = "\033[33m"
FG_WHITE  = "\033[97m"
FG_GREEN  = "\033[32m"

BG_DARK   = "\033[48;5;236m"  # dark-grey bg for code blocks

ERASE_LINE    = "\033[2K"   # erase entire line
CURSOR_COL1   = "\033[1G"   # move cursor to column 1
CURSOR_UP     = "\033[{}A"  # move cursor up N rows


def _wrapped_rows(char_count: int, term_width: int) -> int:
    """Extra terminal rows a raw char_count-wide run wraps onto (0 = fits in one row)."""
    if term_width <= 0 or char_count <= 0:
        return 0
    return max(0, (char_count - 1) // term_width)


def _ansi(codes: str, text: str) -> str:
    return f"{codes}{text}{RESET}"


# ---------------------------------------------------------------------------
# Inline markdown → ANSI
# ---------------------------------------------------------------------------

# Order matters: longer / more-specific patterns first.
_INLINE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # inline code  `…`
    (re.compile(r"`([^`]+)`"), BOLD + FG_YELLOW + r"\1" + RESET),
    # bold+italic ***…*** or ___…___
    (re.compile(r"(\*\*\*|___)(.+?)\1"), BOLD + ITALIC + r"\2" + RESET),
    # bold **…** or __…__
    (re.compile(r"(\*\*|__)(.+?)\1"), BOLD + r"\2" + RESET),
    # italic *…* or _…_  (not inside words to avoid false positives)
    (re.compile(r"(?<!\w)(\*|_)(.+?)\1(?!\w)"), ITALIC + r"\2" + RESET),
    # strikethrough ~~…~~
    (re.compile(r"~~(.+?)~~"), STRIKE + r"\1" + RESET),
]


def _render_inline(text: str) -> str:
    """Apply inline markdown rules to a plain-text string."""
    for pattern, replacement in _INLINE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Line-level rendering
# ---------------------------------------------------------------------------

_HEADING_RE  = re.compile(r"^(#{1,6})\s+(.*)")
_HR_RE       = re.compile(r"^(\*{3,}|-{3,}|={3,})\s*$")
_QUOTE_RE    = re.compile(r"^>\s?(.*)")
_UL_RE       = re.compile(r"^(\s*)[-*+]\s+(.*)")
_OL_RE       = re.compile(r"^(\s*)(\d+[.)]\s+)(.*)")
_FENCE_RE    = re.compile(r"^```")


def _hr_line(width: int = 72, *, unicode: bool = True) -> str:
    char = "─" if unicode else "-"
    return _ansi(DIM, char * width)


def render_line(line: str, *, in_code_block: bool, unicode: bool = True) -> str:
    """Render a single *complete* markdown line to an ANSI string.

    Returns the styled string (without trailing newline).
    ``in_code_block`` governs whether line-level markdown is suppressed.
    """
    if in_code_block:
        return _ansi(FG_YELLOW, line)

    # Horizontal rule
    if _HR_RE.match(line):
        return _hr_line(unicode=unicode)

    # Heading
    m = _HEADING_RE.match(line)
    if m:
        level = len(m.group(1))
        content = _render_inline(m.group(2))
        w = min(len(m.group(2)), 72)
        if level == 1:
            styled = _ansi(BOLD + FG_CYAN, content)
            rule_ch = "═" if unicode else "="
            rule   = _ansi(DIM + FG_CYAN, rule_ch * w)
            return f"{styled}\n{rule}"
        if level == 2:
            styled = _ansi(BOLD + FG_CYAN, content)
            rule_ch = "─" if unicode else "-"
            rule   = _ansi(DIM + FG_CYAN, rule_ch * w)
            return f"{styled}\n{rule}"
        if level == 3:
            return _ansi(BOLD + FG_CYAN, content)
        # h4–h6: same as h3
        return _ansi(BOLD + FG_CYAN, content)

    # Blockquote
    m = _QUOTE_RE.match(line)
    if m:
        inner = _render_inline(m.group(1))
        gutter = _ansi(DIM, ("│" if unicode else "|") + " ")
        return gutter + inner

    # Unordered list
    m = _UL_RE.match(line)
    if m:
        indent = m.group(1)
        content = _render_inline(m.group(2))
        bullet  = _ansi(FG_CYAN, ("•" if unicode else "*"))
        return f"{indent}{bullet} {content}"

    # Ordered list
    m = _OL_RE.match(line)
    if m:
        indent  = m.group(1)
        num     = _ansi(BOLD, m.group(2))
        content = _render_inline(m.group(3))
        return f"{indent}{num}{content}"

    # Plain line — just inline transforms
    return _render_inline(line)


# ---------------------------------------------------------------------------
# Stream renderer
# ---------------------------------------------------------------------------

class MdStreamRenderer:
    """Feed arbitrary text chunks; renders markdown to *stream* in real time.

    Parameters
    ----------
    stream:
        Output file object (default ``sys.stdout``).
    is_tty:
        Override tty detection.  When False the cursor-rewind trick is
        disabled (safe for pipes).
    """

    def __init__(
        self,
        stream: IO[str] | None = None,
        *,
        is_tty: bool | None = None,
    ) -> None:
        self._stream = stream or sys.stdout
        if is_tty is None:
            self._is_tty = hasattr(self._stream, "isatty") and self._stream.isatty()
        else:
            self._is_tty = is_tty
        # Detect whether the stream can handle Unicode box-drawing characters.
        enc = getattr(self._stream, "encoding", None) or "ascii"
        try:
            "═─┌└│•".encode(enc)
            self._unicode = True
        except (UnicodeEncodeError, LookupError):
            self._unicode = False

        self._line_buf: str = ""          # chars of the current (incomplete) line
        self._printed_partial: int = 0    # chars of _line_buf already sent to terminal
        self._in_code_block: bool = False
        self._first_line: bool = True     # track whether we are the very first line

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, chunk: str) -> None:
        """Feed the next chunk of raw markdown text."""
        for ch in chunk:
            if ch == "\n":
                self._flush_line()
            else:
                self._line_buf += ch
                self._print_partial_char(ch)

    def finish(self) -> None:
        """Flush remaining partial line (called when turn ends)."""
        if self._line_buf:
            self._rerender_partial_as_complete()

    def reset(self) -> None:
        """Reset state for a new message (e.g. after finish_turn)."""
        self._line_buf = ""
        self._printed_partial = 0
        self._in_code_block = False
        self._first_line = True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, text: str) -> None:
        self._stream.write(text)
        self._stream.flush()

    def _flush_line(self) -> None:
        """A full line is available in _line_buf — render and emit it."""
        line = self._line_buf
        is_fence = _FENCE_RE.match(line)

        # Erase the partial text we already sent for this line
        self._erase_partial()

        if is_fence:
            self._in_code_block = not self._in_code_block
            if self._in_code_block:
                # Opening fence: print language label dimly
                lang = line[3:].strip()
                if self._unicode:
                    fence_str = _ansi(DIM + FG_YELLOW, "┌─" + (f" {lang}" if lang else "") + " " + "─" * max(0, 40 - len(lang)))
                else:
                    fence_str = _ansi(DIM + FG_YELLOW, "+-" + (f" {lang}" if lang else "") + " " + "-" * max(0, 40 - len(lang)))
                self._write_line(fence_str)
            else:
                # Closing fence
                end_ch = "└" + "─" * 42 if self._unicode else "+" + "-" * 42
                self._write_line(_ansi(DIM + FG_YELLOW, end_ch))
        else:
            rendered = render_line(line, in_code_block=self._in_code_block, unicode=self._unicode)
            self._write_line(rendered)

        # Reset partial tracking for next line
        self._line_buf = ""
        self._printed_partial = 0

    def _write_line(self, rendered: str) -> None:
        """Write a rendered line with a newline, managing first-line spacing."""
        self._write(rendered + "\n")

    def _print_partial_char(self, ch: str) -> None:
        """Print one new char of the partial line (raw, unstyled)."""
        # In a code block, print green; otherwise raw (will be re-rendered)
        if self._in_code_block:
            self._write(_ansi(FG_YELLOW, ch))
        else:
            self._write(ch)
        self._printed_partial += 1

    def _erase_partial(self) -> None:
        """Erase the partial text already printed for the current line."""
        if self._printed_partial == 0:
            return
        if self._is_tty:
            # If the raw partial text wrapped across multiple terminal rows,
            # move the cursor up to the first of those rows before erasing.
            term_width = self._term_width()
            extra_rows = _wrapped_rows(self._printed_partial, term_width)
            seq = ""
            if extra_rows > 0:
                seq += CURSOR_UP.format(extra_rows)
            seq += CURSOR_COL1 + ERASE_LINE
            # Also erase any rows below that still hold wrapped content
            if extra_rows > 0:
                seq += ("".join(f"\n{ERASE_LINE}" for _ in range(extra_rows)))
                seq += CURSOR_UP.format(extra_rows)
            self._write(seq)
        else:
            # Non-tty: can't erase; newline separates raw partial from styled.
            self._write("\n")
        self._printed_partial = 0

    def _term_width(self) -> int:
        """Return current terminal width, with a safe fallback."""
        try:
            import shutil
            return shutil.get_terminal_size().columns or 80
        except Exception:
            return 80

    def _rerender_partial_as_complete(self) -> None:
        """Re-render the partial line as a complete line (for finish())."""
        line = self._line_buf
        if not line:
            return
        self._erase_partial()
        is_fence = _FENCE_RE.match(line)
        if is_fence:
            # Incomplete fence at end — treat as plain
            self._write(line)
        else:
            rendered = render_line(line, in_code_block=self._in_code_block, unicode=self._unicode)
            self._write(rendered)
        self._line_buf = ""
        self._printed_partial = 0
