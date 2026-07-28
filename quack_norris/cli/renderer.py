"""Human-readable output renderer.

Translates AgentOutput events into terminal text. Used in both interactive
and non-interactive modes. Non-interactive mode sends agent text to stdout
and status/tool info to stderr so the output can be piped cleanly.
"""

from __future__ import annotations

import sys

from quack_norris.core.agent import (
    AgentOutput,
    CheckpointOutput,
    TextOutput,
    ThinkingOutput,
    ToolCallOutput,
    ToolResultOutput,
)


class Renderer:
    """Writes agent output to the terminal.

    Parameters
    ----------
    interactive:
        If True, all output goes to stdout (terminal REPL mode).
        If False, agent text goes to stdout, status/tool info to stderr
        (non-interactive / pipe mode).
    show_thinking:
        If True, print <think> blocks. Default False.
    """

    def __init__(self, *, interactive: bool = True, show_thinking: bool = False) -> None:
        self._interactive = interactive
        self._show_thinking = show_thinking
        self._in_thinking = False
        self._in_text = False
        self._after_tool = False  # True after a tool call/result, so we newline before next text

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def on_output(self, item: AgentOutput) -> None:
        if isinstance(item, ThinkingOutput):
            self._handle_thinking(item)
        elif isinstance(item, TextOutput):
            self._handle_text(item)
        elif isinstance(item, ToolCallOutput):
            self._handle_tool_call(item)
        elif isinstance(item, ToolResultOutput):
            self._handle_tool_result(item)
        elif isinstance(item, CheckpointOutput):
            self._handle_checkpoint(item)

    def finish_turn(self) -> None:
        """Call after agent turn completes to ensure trailing newline."""
        if self._in_text or self._in_thinking:
            print(file=self._text_stream())
            self._in_text = False
            self._in_thinking = False
        self._after_tool = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _text_stream(self) -> object:
        return sys.stdout

    def _status_stream(self) -> object:
        return sys.stdout if self._interactive else sys.stderr

    def _handle_thinking(self, item: ThinkingOutput) -> None:
        if not self._show_thinking:
            return
        if not self._in_thinking:
            print("<think>", file=self._text_stream(), flush=True)
            self._in_thinking = True
        print(item.text, end="", file=self._text_stream(), flush=True)

    def _handle_text(self, item: TextOutput) -> None:
        if self._in_thinking:
            print("\n</think>", file=self._text_stream())
            self._in_thinking = False
        if self._after_tool:
            print(file=self._text_stream())  # blank line after tool block before response
            self._after_tool = False
        self._in_text = True
        print(item.text, end="", file=self._text_stream(), flush=True)

    def _handle_checkpoint(self, item: CheckpointOutput) -> None:
        if self._in_text:
            print(file=self._text_stream())
            self._in_text = False
        print(
            f"\n  ◆ checkpoint — {item.replaced_count} messages summarised, "
            f"~{item.tokens_before:,} → ~{item.tokens_after:,} tokens",
            file=self._status_stream(),
            flush=True,
        )
        self._after_tool = True

    def _handle_tool_call(self, item: ToolCallOutput) -> None:
        if self._in_text:
            print(file=self._text_stream())
            self._in_text = False
        if item.needs_approval is False:
            # Auto-approved — print compact multi-line block now.
            args = _format_args_multiline(item.arguments, truncate=True)
            if args:
                print(f"\n  ⚡ {item.tool_name}\n{args}", file=self._status_stream(), flush=True)
            else:
                print(f"\n  ⚡ {item.tool_name}", file=self._status_stream(), flush=True)
            self._after_tool = True
        # For needs_approval=True/"human", approval.py prints the badge + args.

    def _handle_tool_result(self, item: ToolResultOutput) -> None:
        content = item.result.content or ""
        if item.result.is_error:
            # Denials already printed by approval.py — skip duplicate.
            if not content.startswith("Tool call was denied"):
                lines = content.splitlines()
                first = f"  ❌ {lines[0]}" if lines else "  ❌"
                rest = "\n".join(f"     {line}" for line in lines[1:])
                output = f"{first}\n{rest}" if rest else first
                print(output, file=self._status_stream(), flush=True)
        elif item.show_output and content.strip():
            # Check for background-promotion message — show a compact status
            # line instead of the full multi-line instruction block.
            display = _maybe_format_background(content) or content
            indented = "\n".join(f"     {line}" for line in display.splitlines())
            print(f"\n{indented}", file=self._status_stream(), flush=True)
        self._after_tool = True


def _format_args_multiline(arguments: dict, *, truncate: bool = True, indent: str = "       ") -> str:
    """Format arguments as aligned multi-line key = value pairs.

    Single-line values are shown without quotes:

        path       = AGENTS.md

    Multi-line values have their first content line on the key line; every
    subsequent line is indented to align under the first value character:

        new_string = this
                     is a
                     multiline
                     string

    Parameters
    ----------
    arguments:
        Tool argument dict.
    truncate:
        If True, values longer than 120 chars total are truncated with '...'
        on the last displayed line.
        If False, values are shown in full (used for human approval prompts).
    indent:
        Leading whitespace for each arg line.
    """
    if not arguments:
        return ""
    max_key = max(len(k) for k in arguments)
    # Width of the prefix that appears before the value on the first line:
    # indent  +  padded key  +  " = "  (3 chars)
    prefix_len = len(indent) + max_key + 3
    continuation_indent = " " * prefix_len
    lines = []
    for k, v in arguments.items():
        v_str = str(v)
        v_lines = v_str.splitlines() or [""]
        if truncate and len(v_str) > 120:
            kept: list[str] = []
            budget = 117  # leave 3 chars for the ellipsis
            for vl in v_lines:
                if budget <= 0:
                    break
                kept.append(vl[:budget])
                budget -= len(vl) + 1  # +1 for the newline separator
            v_lines = kept
            v_lines[-1] = v_lines[-1].rstrip() + "..."
        prefix = f"{indent}{k:<{max_key}} = "
        first_line = f"{prefix}{v_lines[0]}"
        rest = [f"{continuation_indent}{vl}" for vl in v_lines[1:]]
        lines.append("\n".join([first_line] + rest))
    return "\n".join(lines)


def _maybe_format_background(content: str) -> str | None:
    """If *content* is a background-promotion message, return a compact one-liner.

    The shell tool returns a multi-line instruction block like:
        Process still running after 30s.  Handle: bg-3f2a
        Use check_tool(handle='bg-3f2a') to ...

    We replace that with a single clean status badge for the terminal.
    Returns ``None`` when the content is not a background-promotion message.
    """
    import re
    m = re.match(r"Process still running after \d+s\.\s+Handle:\s+(bg-\w+)", content)
    if m:
        handle = m.group(1)
        return f"⏳ still running — handle: {handle}"
    # Also handle check_tool "still running" status lines emitted by the tool itself
    if content.startswith("⏳ still running"):
        return content
    return None
