"""Tests for the stream markdown renderer."""
from __future__ import annotations

import io
from quack_norris.cli.md_stream_renderer import MdStreamRenderer, render_line


def _render(md: str, *, is_tty: bool = True) -> str:
    """Render markdown string through MdStreamRenderer, return the output."""
    buf = io.StringIO()
    r = MdStreamRenderer(buf, is_tty=is_tty)
    for ch in md:
        r.feed(ch)
    r.finish()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# render_line unit tests
# ---------------------------------------------------------------------------

def test_h1():
    out = render_line("# Hello", in_code_block=False)
    assert "Hello" in out
    assert "═" in out  # rule under h1


def test_h2():
    out = render_line("## Sub", in_code_block=False)
    assert "Sub" in out
    assert "─" in out  # rule under h2


def test_h3():
    out = render_line("### Deep", in_code_block=False)
    assert "Deep" in out
    # h3 has no rule
    assert "─" not in out
    assert "═" not in out
    assert "\033[36m" in out  # FG_CYAN (same colour as h2)


def test_bold():
    out = render_line("This is **bold** text", in_code_block=False)
    assert "bold" in out
    assert "\033[1m" in out  # BOLD escape


def test_inline_code():
    out = render_line("Try `some code` here", in_code_block=False)
    assert "some code" in out
    assert "\033[33m" in out  # FG_YELLOW


def test_strikethrough():
    out = render_line("This ~~was~~ removed", in_code_block=False)
    assert "was" in out
    assert "\033[9m" in out  # STRIKE


def test_italic():
    out = render_line("This is *italic* here", in_code_block=False)
    assert "italic" in out
    assert "\033[3m" in out  # ITALIC


def test_hr():
    out = render_line("---", in_code_block=False)
    assert "─" in out


def test_blockquote():
    out = render_line("> A quote", in_code_block=False)
    assert "A quote" in out
    assert "│" in out


def test_ul():
    out = render_line("- item", in_code_block=False)
    assert "item" in out
    assert "•" in out


def test_ol():
    out = render_line("1. first", in_code_block=False)
    assert "first" in out
    assert "\033[1m" in out  # number is bold


def test_code_block_line_passthrough():
    out = render_line("def foo():", in_code_block=True)
    # No markdown transforms inside code block
    assert "def foo():" in out
    assert "\033[33m" in out  # FG_YELLOW


def test_code_block_no_bold():
    out = render_line("**not bold**", in_code_block=True)
    assert "\033[1m" not in out  # no bold in code block


# ---------------------------------------------------------------------------
# MdStreamRenderer integration tests
# ---------------------------------------------------------------------------

def test_stream_h1_complete():
    buf = io.StringIO()
    r = MdStreamRenderer(buf, is_tty=True)
    r._unicode = True  # force unicode mode
    for ch in "# Title\n":
        r.feed(ch)
    r.finish()
    out = buf.getvalue()
    assert "Title" in out
    assert "═" in out  # rule under h1


def test_stream_code_fence():
    md = "```python\ndef f(): pass\n```\n"
    buf = io.StringIO()
    r = MdStreamRenderer(buf, is_tty=True)
    r._unicode = True
    for ch in md:
        r.feed(ch)
    r.finish()
    out = buf.getvalue()
    assert "def f(): pass" in out
    assert "┌" in out  # opening fence
    assert "└" in out  # closing fence


def test_stream_partial_finish():
    """finish() without trailing newline should still render."""
    out = _render("**bold**")  # no trailing \n
    assert "bold" in out
    assert "\033[1m" in out


def test_stream_reset():
    buf = io.StringIO()
    r = MdStreamRenderer(buf, is_tty=True)
    r.feed("# H1\n")
    r.finish()
    r.reset()
    r.feed("## H2\n")
    r.finish()
    out = buf.getvalue()
    assert "H1" in out
    assert "H2" in out
    assert not r._in_code_block  # reset cleared state


def test_tty_erase_on_completed_line():
    """On tty, partial raw text is erased before styled version is written."""
    buf = io.StringIO()
    r = MdStreamRenderer(buf, is_tty=True)
    r.feed("**bold**\n")
    out = buf.getvalue()
    # CURSOR_COL1 + ERASE_LINE should appear (erase escape)
    assert "\033[2K" in out
    assert "\033[1G" in out


def test_non_tty_no_erase():
    """On non-tty, no ANSI cursor escapes are emitted."""
    buf = io.StringIO()
    r = MdStreamRenderer(buf, is_tty=False)
    r.feed("hello\n")
    out = buf.getvalue()
    assert "\033[2K" not in out
    assert "\033[1G" not in out


def test_ascii_fallback():
    """Unicode=False falls back to ASCII art."""
    out = render_line("# Title", in_code_block=False, unicode=False)
    assert "=" in out
    assert "═" not in out

    out = render_line("- item", in_code_block=False, unicode=False)
    assert "*" in out  # ASCII bullet
    assert "•" not in out
