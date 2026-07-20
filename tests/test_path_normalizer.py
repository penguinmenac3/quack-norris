"""Tests for path normalisation helpers and the attach_path_normalizer hook."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import pytest

from quack_norris.core.llm.tool import Param, ToolResult, tool
from quack_norris.tools.files import (
    _to_relative,
    _rewrite_args,
    _rewrite_content,
    attach_path_normalizer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Use a cross-platform absolute path anchored at the real temp dir so that
# Path.is_absolute() is always True on both Windows and POSIX.
import tempfile
_TMP = Path(tempfile.gettempdir()).resolve()
ROOT = _TMP / "project" / "root"

def _abs(rel: str) -> str:
    """Return an absolute path string inside ROOT (uses OS-native separators)."""
    return str(ROOT / rel)


# ---------------------------------------------------------------------------
# _to_relative
# ---------------------------------------------------------------------------

class TestToRelative:
    def test_absolute_inside_root(self):
        assert _to_relative(_abs("foo/bar.py"), ROOT) == "foo/bar.py"

    def test_absolute_equals_root(self):
        assert _to_relative(str(ROOT), ROOT) == "."

    def test_absolute_outside_root(self):
        outside = str(_TMP / "other" / "file.py")
        result = _to_relative(outside, ROOT)
        assert result == outside   # unchanged — outside the root

    def test_relative_passthrough(self):
        assert _to_relative("foo/bar.py", ROOT) == "foo/bar.py"

    def test_relative_backslash_normalised(self):
        # Relative paths with backslashes get forward-slash normalisation.
        assert _to_relative("foo\\bar.py", ROOT) == "foo/bar.py"

    def test_nested_inside_root(self):
        assert _to_relative(_abs("a/b/c.txt"), ROOT) == "a/b/c.txt"

    def test_empty_string_passthrough(self):
        # Empty string is not a path — should come back unchanged.
        assert _to_relative("", ROOT) == ""


# ---------------------------------------------------------------------------
# _rewrite_args
# ---------------------------------------------------------------------------

class TestRewriteArgs:
    def test_rewrites_absolute_path_value(self):
        args = {"path": _abs("foo.py"), "content": "hello"}
        result = _rewrite_args(args, ROOT)
        assert result["path"] == "foo.py"
        assert result["content"] == "hello"   # non-path string untouched

    def test_leaves_relative_paths(self):
        args = {"path": "foo/bar.py"}
        assert _rewrite_args(args, ROOT)["path"] == "foo/bar.py"

    def test_leaves_non_string_values(self):
        args = {"offset": 5, "limit": 200}
        assert _rewrite_args(args, ROOT) == {"offset": 5, "limit": 200}

    def test_does_not_mutate_original(self):
        original_path = _abs("x.py")
        args = {"path": original_path}
        _rewrite_args(args, ROOT)
        assert args["path"] == original_path  # original unchanged


# ---------------------------------------------------------------------------
# _rewrite_content
# ---------------------------------------------------------------------------

class TestRewriteContent:
    def test_strips_root_prefix_from_content(self):
        import os
        content = f"Created {_abs('foo/bar.py')} (42 bytes)"
        result = _rewrite_content(content, ROOT)
        assert str(ROOT) not in result
        # The relative tail is present; separator style is platform-dependent
        assert "foo" in result and "bar.py" in result

    def test_no_root_in_content_unchanged(self):
        content = "hello world"
        assert _rewrite_content(content, ROOT) == "hello world"

    def test_multiple_occurrences(self):
        content = f"{_abs('a.py')} and {_abs('b.py')}"
        result = _rewrite_content(content, ROOT)
        assert str(ROOT) not in result
        assert "a.py" in result
        assert "b.py" in result

    def test_root_itself_becomes_dot(self):
        content = f"Working in {ROOT}"
        result = _rewrite_content(content, ROOT)
        assert "." in result
        assert str(ROOT) not in result


# ---------------------------------------------------------------------------
# attach_path_normalizer — hook wiring and end-to-end behaviour
# ---------------------------------------------------------------------------

class TestAttachPathNormalizer:
    def test_hooks_are_attached(self):
        @tool
        def dummy(path: Annotated[str, Param("A path")]) -> ToolResult:
            """Dummy tool."""
            return ToolResult(content=f"got {path}")

        assert dummy.pre_execute_hook is None
        assert dummy.post_execute_hook is None

        attach_path_normalizer([dummy], lambda: ROOT)

        assert dummy.pre_execute_hook is not None
        assert dummy.post_execute_hook is not None

    @pytest.mark.asyncio
    async def test_pre_hook_rewrites_absolute_arg(self):
        received: list[str] = []

        @tool
        def capture(path: Annotated[str, Param("path")]) -> ToolResult:
            """Capture the path argument."""
            received.append(path)
            return ToolResult(content=f"ok {path}")

        attach_path_normalizer([capture], lambda: ROOT)

        await capture.execute(path=_abs("myfile.py"))
        assert received == ["myfile.py"]

    @pytest.mark.asyncio
    async def test_post_hook_rewrites_output_content(self):
        @tool
        def emit(path: Annotated[str, Param("path")]) -> ToolResult:
            """Return content with absolute path."""
            return ToolResult(content=f"Created {_abs('out.py')} (10 bytes)")

        attach_path_normalizer([emit], lambda: ROOT)

        result = await emit.execute(path="whatever")
        assert str(ROOT) not in result.content
        assert "out.py" in result.content

    @pytest.mark.asyncio
    async def test_relative_arg_passes_through_unchanged(self):
        received: list[str] = []

        @tool
        def capture2(path: Annotated[str, Param("path")]) -> ToolResult:
            """Capture."""
            received.append(path)
            return ToolResult(content="ok")

        attach_path_normalizer([capture2], lambda: ROOT)

        await capture2.execute(path="sub/file.py")
        assert received == ["sub/file.py"]

    @pytest.mark.asyncio
    async def test_is_error_preserved_through_post_hook(self):
        @tool
        def failing(path: Annotated[str, Param("p")]) -> ToolResult:
            """Fails."""
            return ToolResult(content=f"Error at {_abs('x.py')}", is_error=True)

        attach_path_normalizer([failing], lambda: ROOT)

        result = await failing.execute(path="x.py")
        assert result.is_error is True
        assert str(ROOT) not in result.content


# ---------------------------------------------------------------------------
# Tool.pre_execute_hook / post_execute_hook — generic hook mechanism
# ---------------------------------------------------------------------------

class TestToolHooks:
    @pytest.mark.asyncio
    async def test_pre_hook_can_modify_args(self):
        @tool
        def upcase(text: Annotated[str, Param("text")]) -> str:
            """Return text."""
            return text

        def shout(args):
            return {k: v.upper() if isinstance(v, str) else v for k, v in args.items()}

        upcase.pre_execute_hook = shout
        result = await upcase.execute(text="hello")
        assert result.content == "HELLO"

    @pytest.mark.asyncio
    async def test_post_hook_can_modify_result(self):
        @tool
        def greet(name: Annotated[str, Param("name")]) -> str:
            """Greet."""
            return f"Hello, {name}!"

        def wrap(r: ToolResult) -> ToolResult:
            return ToolResult(content=f"[wrapped] {r.content}", is_error=r.is_error)

        greet.post_execute_hook = wrap
        result = await greet.execute(name="World")
        assert result.content == "[wrapped] Hello, World!"

    @pytest.mark.asyncio
    async def test_async_pre_hook_is_awaited(self):
        @tool
        def identity(x: Annotated[str, Param("x")]) -> str:
            """Return x."""
            return x

        import asyncio

        async def async_pre(args):
            await asyncio.sleep(0)
            return {k: v + "_modified" if isinstance(v, str) else v for k, v in args.items()}

        identity.pre_execute_hook = async_pre
        result = await identity.execute(x="hello")
        assert result.content == "hello_modified"

    @pytest.mark.asyncio
    async def test_async_post_hook_is_awaited(self):
        @tool
        def const() -> str:
            """Return constant."""
            return "original"

        import asyncio

        async def async_post(r: ToolResult) -> ToolResult:
            await asyncio.sleep(0)
            return ToolResult(content="async_replaced", is_error=r.is_error)

        const.post_execute_hook = async_post
        result = await const.execute()
        assert result.content == "async_replaced"

    @pytest.mark.asyncio
    async def test_no_hooks_by_default(self):
        @tool
        def plain() -> str:
            """Plain tool."""
            return "plain"

        assert plain.pre_execute_hook is None
        assert plain.post_execute_hook is None
        result = await plain.execute()
        assert result.content == "plain"
