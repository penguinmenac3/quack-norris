"""File system tools.

Flat tool set (no subcommands) so LLMs can select operations without ambiguity.

All tools are built via ``make_file_tools(get_cwd)`` so relative paths resolve
against the session's current working directory (meta.cwd) rather than the
process CWD.

Requires approval (auto-approved by the CLI if path is within project root):
  file_view       — read a file with line numbers, or list a directory
                    (escalates to user if path resolves outside project root)

Requires approval (write/destructive; auto-approved inside the current
session's ``overflow/`` dir, which holds agent-owned scratch data — the
tool-output overflow files — when ``make_file_tools`` is given a session_id):
  file_write      — create a new file (fails if already exists)
  file_str_replace — edit a file in-place by exact string replacement
  file_move       — move or rename a file/directory
  file_delete     — delete a file or empty directory
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from quack_norris.core.llm import Param, ToolResult, Tool, tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n}{unit}"
        n //= 1024
    return f"{n}TB"


def _resolve(path: str, base: Path) -> Path:
    """Resolve path relative to base (meta.cwd). Absolute paths pass through."""
    p = Path(path)
    return (base / p).resolve() if not p.is_absolute() else p.resolve()


def _is_outside(p: Path, root: Path) -> bool:
    """Return True if p is not inside root."""
    try:
        p.relative_to(root)
        return False
    except ValueError:
        return True


def _to_relative(text: str, root: Path) -> str:
    """Normalise *text* so the agent always sees forward-slash relative paths.

    Rules
    -----
    * If *text* is an absolute path whose prefix matches *root*, strip the
      prefix and return the remainder with forward slashes (e.g. ``foo/bar.py``).
    * If the path equals *root* exactly, return ``"."`` (never an empty string).
    * Already-relative paths get backslashes normalised to forward slashes.
    * Strings that don't look like paths (contain newlines etc.) are returned
      unchanged so content/old_string/new_string args are never mangled.
    """
    # Don't mangle multiline strings — they're content, not paths.
    if "\n" in text or "\r" in text:
        return text
    try:
        p = Path(text)
        if p.is_absolute():
            try:
                rel = p.relative_to(root)
                rel_str = str(rel).replace("\\", "/")
                return rel_str if rel_str else "."
            except ValueError:
                return text  # outside root — leave unchanged
        else:
            # Already relative — just normalise separators.
            return text.replace("\\", "/")
    except Exception:
        return text


def _rewrite_args(arguments: dict, root: Path) -> dict:
    """Return a copy of *arguments* with root-prefix stripped from all string values."""
    return {
        k: _to_relative(v, root) if isinstance(v, str) else v
        for k, v in arguments.items()
    }


def _rewrite_content(content: str, root: Path) -> str:
    """Replace every occurrence of the absolute *root* prefix in *content*.

    Only the path *prefix* itself is normalised to forward slashes; the rest
    of *content* is left untouched so that backslash escape sequences
    (e.g. ``\\n`` in source-code snippets) are never mangled.
    """
    # Build both slash-style variants of the root so we catch mixed output.
    root_fwd = str(root).replace("\\", "/")   # C:/Users/foo/project
    root_bwd = str(root).replace("/", "\\")   # C:\Users\foo\project

    for prefix in (root_fwd, root_bwd):
        if prefix not in content:
            continue
        # prefix + separator → empty (relative tail follows)
        content = content.replace(prefix + "/", "")
        content = content.replace(prefix + "\\", "")
        # bare root (no trailing sep) → "."
        content = content.replace(prefix, ".")
    # No global backslash→slash pass: that would corrupt \n, \t, etc.
    return content


def attach_path_normalizer(tools: "list[Tool]", get_root: "Callable[[], Path]") -> None:
    """Attach path-normalisation hooks to each tool in *tools* in-place.

    After this call every tool will:

    * **Before execution** — rewrite any string argument whose value is an
      absolute path inside *get_root()* to a clean relative path with forward
      slashes (e.g. ``"foo/bar.py"`` instead of ``"C:/project/foo/bar.py"``).
      This means the agent can pass absolute paths and the tool will silently
      correct them; the underlying file functions receive the relative form they
      already handle correctly via ``_resolve``.

    * **After execution** — replace every occurrence of the project root prefix
      in ``ToolResult.content`` with the relative equivalent so the LLM never
      sees absolute project-internal paths in tool output either.

    Parameters
    ----------
    tools:
        List of :class:`~quack_norris.core.llm.Tool` instances to patch.
    get_root:
        Callable that returns the current project root ``Path``.  Called
        lazily on every tool invocation so session ``switch_project`` is
        automatically reflected.
    """
    def _pre(arguments: dict) -> dict:
        return _rewrite_args(arguments, get_root())

    def _post(result: "ToolResult") -> "ToolResult":
        rewritten = _rewrite_content(result.content, get_root())
        if rewritten is result.content:
            return result
        return ToolResult(content=rewritten, is_error=result.is_error)

    for t in tools:
        t.pre_execute_hook = _pre
        t.post_execute_hook = _post


# ---------------------------------------------------------------------------
# Factory — builds all file tools bound to a get_cwd callable
# ---------------------------------------------------------------------------

def make_file_tools(
    get_cwd: Callable[[], Path],
    session_id: str | None = None,
) -> list[Tool]:
    """Return file tool instances that resolve relative paths against get_cwd().

    When *session_id* is given, file operations confined to that session's
    overflow directory (``<session>/overflow/``) are auto-approved: it holds
    agent-owned scratch data (spilled tool output), so the agent may freely
    read, write and delete there.
    """

    def _in_overflow_dir(p: Path) -> bool:
        if session_id is None:
            return False
        from quack_norris.cli.session import overflow_dir
        return not _is_outside(p, overflow_dir(session_id))

    # -----------------------------------------------------------------------
    # file_view — read file or list directory (auto-approved within project root)
    # -----------------------------------------------------------------------

    def _file_view_needs_approval(args: dict):
        p = _resolve(args.get("path") or ".", get_cwd())
        if _in_overflow_dir(p):
            return False
        return True if _is_outside(p, get_cwd()) else False

    def _needs_approval_outside_overflow(*arg_names: str):
        """Approval predicate: auto-approve only if every path arg is in the overflow dir."""
        def _predicate(args: dict):
            paths = [args.get(name) for name in arg_names]
            if not all(paths):
                return True
            return not all(_in_overflow_dir(_resolve(p, get_cwd())) for p in paths)
        return _predicate

    @tool(needs_approval=_file_view_needs_approval)
    def file_view(
        path: Annotated[str, Param("Relative or absolute path to a file or directory — use a relative path (e.g. 'foo/bar.py'); absolute paths are only acceptable when the target is outside the project root")],
        offset: Annotated[int, Param("First line to show when viewing a file (1-indexed, default 1)")] = 1,
        limit: Annotated[int, Param("Maximum lines to show when viewing a file (default 200, max 500)")] = 200,
    ) -> ToolResult:
        """View a file with line numbers, or list the contents of a directory.

        Relative paths resolve against the current project directory.
        Reading outside the project root requires explicit user approval.
        """
        cwd = get_cwd()
        p = _resolve(path or ".", cwd)
        if not p.exists():
            return ToolResult(content=f"Not found: {path}", is_error=True)

        if p.is_dir():
            try:
                entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
                lines = []
                for entry in entries:
                    if entry.is_dir():
                        lines.append(f"  {entry.name}/")
                    else:
                        lines.append(f"  {entry.name}  ({_human_size(entry.stat().st_size)})")
                return ToolResult(content=f"{_to_relative(str(p), cwd)}\n" + ("\n".join(lines) if lines else "  (empty)"))
            except Exception as exc:  # noqa: BLE001
                return ToolResult(content=str(exc), is_error=True)

        try:
            # Normalise CRLF → LF so the LLM always sees plain \n line endings.
            raw = p.read_text(encoding="utf-8", errors="replace")
            text_lines = raw.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(content=str(exc), is_error=True)

        eff_offset = max(1, offset)
        eff_limit = min(max(1, limit), 500)
        slice_ = text_lines[eff_offset - 1 : eff_offset - 1 + eff_limit]
        numbered = "\n".join(f"{eff_offset + i:>4}  {line}" for i, line in enumerate(slice_))
        end_line = eff_offset + len(slice_) - 1
        header = f"// {_to_relative(str(p), cwd)}  ({len(text_lines)} lines total, showing {eff_offset}-{end_line})\n"
        return ToolResult(content=header + numbered)

    # -----------------------------------------------------------------------
    # file_write — create new file (approval required)
    # -----------------------------------------------------------------------

    @tool(needs_approval=_needs_approval_outside_overflow("path"))
    def file_write(
        path: Annotated[str, Param("Relative or absolute path for the new file — use a relative path (e.g. 'foo/bar.py'); absolute paths are only acceptable when the target is outside the project root")],
        content: Annotated[str, Param("Full content to write to the file")],
    ) -> ToolResult:
        """Create a new file with the given content. Fails if the file already exists.

        If you need to overwrite an existing file, use file_str_replace to edit it
        in place, or file_delete first then file_write.
        """
        p = _resolve(path, get_cwd())
        if p.exists():
            tmp_hash = hashlib.sha1(content.encode()).hexdigest()[:8]
            tmp_path = Path(tempfile.gettempdir()) / f"quack_{tmp_hash}"
            tmp_path.write_text(content, encoding="utf-8")
            return ToolResult(
                content=(
                    f"File already exists: {p}\n"
                    f"Content saved to temp file: {tmp_path}\n"
                    "Use file_str_replace to edit in place, or file_delete then file_write to overwrite."
                ),
                is_error=True,
            )
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(content=f"Created {_to_relative(str(p), get_cwd())} ({len(content)} bytes)")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(content=str(exc), is_error=True)

    # -----------------------------------------------------------------------
    # file_str_replace — edit in-place (approval required)
    # -----------------------------------------------------------------------

    @tool(needs_approval=_needs_approval_outside_overflow("path"))
    def file_str_replace(
        path: Annotated[str, Param("Relative or absolute path to the file to edit — use a relative path (e.g. 'foo/bar.py'); absolute paths are only acceptable when the target is outside the project root")],
        old_string: Annotated[str, Param("Exact string to find (must be unique in the file)")],
        new_string: Annotated[str, Param("Replacement string")],
    ) -> ToolResult:
        """Replace an exact string in a file. The old_string must appear exactly once."""
        p = _resolve(path, get_cwd())
        if not p.exists():
            return ToolResult(content=f"File not found: {p}", is_error=True)
        try:
            # Normalise CRLF → LF so comparisons with \n-only strings always work.
            original = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(content=str(exc), is_error=True)

        count = original.count(old_string)
        if count == 0:
            return ToolResult(content=f"String not found in {_to_relative(str(p), get_cwd())}:\n{old_string!r}", is_error=True)
        if count > 1:
            return ToolResult(
                content=f"String appears {count} times in {_to_relative(str(p), get_cwd())} — provide more context to make it unique.",
                is_error=True,
            )

        updated = original.replace(old_string, new_string, 1)
        try:
            p.write_text(updated, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(content=str(exc), is_error=True)
        return ToolResult(content=f"Replaced 1 occurrence in {_to_relative(str(p), get_cwd())}")

    # -----------------------------------------------------------------------
    # file_move — move or rename (approval required)
    # -----------------------------------------------------------------------

    @tool(needs_approval=_needs_approval_outside_overflow("source", "destination"))
    def file_move(
        source: Annotated[str, Param("Relative or absolute path to move from — use a relative path (e.g. 'foo/bar.py'); absolute paths are only acceptable when the source is outside the project root")],
        destination: Annotated[str, Param("Relative or absolute path to move to — use a relative path (e.g. 'foo/bar.py'); absolute paths are only acceptable when the destination is outside the project root")],
    ) -> ToolResult:
        """Move or rename a file or directory."""
        cwd = get_cwd()
        src = _resolve(source, cwd)
        dst = _resolve(destination, cwd)
        if not src.exists():
            return ToolResult(content=f"Source not found: {src}", is_error=True)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return ToolResult(content=f"Moved {_to_relative(str(src), cwd)} → {_to_relative(str(dst), cwd)}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(content=str(exc), is_error=True)

    # -----------------------------------------------------------------------
    # file_delete — delete file or empty dir (approval required)
    # -----------------------------------------------------------------------

    @tool(needs_approval=_needs_approval_outside_overflow("path"))
    def file_delete(
        path: Annotated[str, Param("Relative or absolute path to delete — use a relative path (e.g. 'foo/bar.py'); absolute paths are only acceptable when the target is outside the project root")],
    ) -> ToolResult:
        """Delete a file. Use the shell tool (rm -rf) to delete non-empty directories."""
        p = _resolve(path, get_cwd())
        if not p.exists():
            return ToolResult(content=f"Not found: {p}", is_error=True)
        try:
            if p.is_file() or p.is_symlink():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
            else:
                return ToolResult(content=f"Cannot delete: {p} is not a file or directory", is_error=True)
            return ToolResult(content=f"Deleted {_to_relative(str(p), get_cwd())}")
        except OSError as exc:
            return ToolResult(content=str(exc), is_error=True)

    tools = [file_view, file_write, file_str_replace, file_move, file_delete]
    attach_path_normalizer(tools, get_cwd)
    return tools


# ---------------------------------------------------------------------------
# Convenience singletons for callers that don't need session context
# (resolve against process CWD — kept for backward compatibility)
# ---------------------------------------------------------------------------

_process_cwd_tools = make_file_tools(lambda: Path.cwd())
file_view, file_write, file_str_replace, file_move, file_delete = _process_cwd_tools
