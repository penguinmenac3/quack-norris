"""Tests for the @tool decorator."""

from __future__ import annotations

from typing import Annotated

import pytest

from quack_norris.core.llm.tool import Param, Tool, ToolResult, tool

# ---------------------------------------------------------------------------
# Tool definitions used across tests
# ---------------------------------------------------------------------------

@tool
async def add(
    x: Annotated[int, Param("First operand")],
    y: Annotated[int, Param("Second operand")],
) -> int:
    """Add two numbers."""
    return x + y


@tool
async def greet(
    name: Annotated[str, Param("Name to greet")],
) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"


@tool(needs_approval=True)
async def risky(
    path: Annotated[str, Param("Path to delete")],
) -> str:
    """Delete something dangerous."""
    return f"deleted {path}"


@tool
def sync_upper(
    text: Annotated[str, Param("Text to uppercase")],
) -> str:
    """Uppercase a string (sync function)."""
    return text.upper()


@tool(truncation_allowed=False)
def load_instructions() -> str:
    """Return instructions that must not be clipped."""
    return "step 1 ... step 99"


def test_truncation_allowed_defaults_to_true() -> None:
    assert add.truncation_allowed is True
    assert risky.truncation_allowed is True


def test_truncation_allowed_can_be_opted_out() -> None:
    assert load_instructions.truncation_allowed is False


@tool
async def with_default(
    text: Annotated[str, Param("Input text")],
    prefix: Annotated[str, Param("Optional prefix")] = ">>",
) -> str:
    """Prepend a prefix."""
    return f"{prefix} {text}"


@tool
async def with_enum(
    direction: Annotated[str, Param("Direction", enum=["north", "south", "east", "west"])],
) -> str:
    """Move in a direction."""
    return direction


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

def test_tool_is_tool_instance() -> None:
    assert isinstance(add, Tool)
    assert isinstance(greet, Tool)


def test_tool_name() -> None:
    assert add.name == "add"
    assert greet.name == "greet"


def test_tool_description_from_docstring() -> None:
    assert add.description == "Add two numbers."
    assert greet.description == "Return a greeting."


def test_param_descriptions() -> None:
    assert add.parameters["x"]["description"] == "First operand"
    assert add.parameters["y"]["description"] == "Second operand"
    assert greet.parameters["name"]["description"] == "Name to greet"


def test_param_types() -> None:
    assert add.parameters["x"]["type"] == "integer"
    assert add.parameters["y"]["type"] == "integer"
    assert greet.parameters["name"]["type"] == "string"


def test_required_no_defaults() -> None:
    assert add.required == ["x", "y"]
    assert greet.required == ["name"]


def test_required_with_defaults() -> None:
    assert with_default.required == ["text"]
    assert "prefix" not in with_default.required


def test_enum_in_parameters() -> None:
    assert with_enum.parameters["direction"]["enum"] == ["north", "south", "east", "west"]


def test_no_enum_when_not_specified() -> None:
    assert "enum" not in add.parameters["x"]


def test_needs_approval_default_false() -> None:
    assert add.needs_approval is False
    assert greet.needs_approval is False


def test_needs_approval_explicit() -> None:
    assert risky.needs_approval is True


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_async() -> None:
    result = await add.execute(x=3, y=4)
    assert isinstance(result, ToolResult)
    assert result.content == "7"
    assert result.is_error is False


@pytest.mark.asyncio
async def test_execute_string_tool() -> None:
    result = await greet.execute(name="World")
    assert result.content == "Hello, World!"


@pytest.mark.asyncio
async def test_execute_sync_tool() -> None:
    result = await sync_upper.execute(text="hello")
    assert result.content == "HELLO"


@pytest.mark.asyncio
async def test_execute_with_default() -> None:
    result = await with_default.execute(text="hi")
    assert result.content == ">> hi"

    result2 = await with_default.execute(text="hi", prefix="--")
    assert result2.content == "-- hi"


@pytest.mark.asyncio
async def test_execute_error_captured() -> None:
    @tool
    async def boom() -> str:
        """Always raises."""
        raise ValueError("kaboom")

    result = await boom.execute()
    assert result.is_error is True
    assert "kaboom" in result.content


# ---------------------------------------------------------------------------
# Plain annotations still work (no Param wrapper)
# ---------------------------------------------------------------------------

@tool
async def plain(x: int, y: str) -> str:
    """Plain annotations without Param."""
    return f"{x}-{y}"


def test_plain_annotations_fallback() -> None:
    assert plain.parameters["x"]["type"] == "integer"
    assert plain.parameters["x"]["description"] == ""
    assert plain.parameters["y"]["type"] == "string"
