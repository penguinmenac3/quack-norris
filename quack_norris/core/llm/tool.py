"""Tool base class, ``Param`` metadata, and ``@tool`` decorator.

Lives in ``quack_norris.core.llm`` so the LLM layer can accept tools directly
without depending on the agent layer.

Usage::

    from typing import Annotated
    from quack_norris.core.llm import Tool, Param, tool

    @tool
    def read_file(
        path: Annotated[str, Param("Absolute path to read")],
    ) -> str:
        '''Read a file and return its contents.'''
        return open(path).read()

    @tool(needs_approval=True)
    async def delete_file(
        path: Annotated[str, Param("Absolute path to delete")],
    ) -> str:
        '''Delete a file from disk.'''
        import os; os.remove(path)
        return f"Deleted {path}"

    # Use with LLM directly (no agent loop needed):
    stream = await LLM.converse(model="ollama/qwen3:14b", ..., tools=[read_file])
    async for item in stream:
        if isinstance(item, ToolCallRequest):
            result = await item.execute()   # item already knows which function to call

    # Or pass to the agent loop as usual:
    await agent(..., tools=[read_file, delete_file], ...)
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, get_args, get_origin, get_type_hints

# Three-state approval decision:
#   False       — execute immediately, no approval needed
#   True        — check whitelist, then ask human if not whitelisted
#   "human"     — skip whitelist, always ask human
ApprovalState = bool | Literal["human"]

# ---------------------------------------------------------------------------
# ToolResult — returned by tool execution
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    """Returned by a tool implementation."""

    content: str
    is_error: bool = False


# ---------------------------------------------------------------------------
# ToolCallRequest — emitted by the LLM stream when a tool should be called
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRequest:
    """The model wants to call a tool.

    When produced by :meth:`LLM.converse`, ``execute``, ``needs_approval``,
    and ``approval_display`` are bound to the matched :class:`Tool`
    so callers can act without keeping a separate tool map::

        async for item in stream:
            if isinstance(item, ToolCallRequest):
                if item.needs_approval:
                    if not await ask_user(item.approval_display()):
                        continue
                result = await item.execute()
    """

    id: str
    name: str
    arguments: dict[str, Any]
    # Bound at stream-time when a matching Tool is found; None when used
    # as a raw wire type (e.g. inside chat history AssistantMessage).
    execute: Callable[..., Awaitable[ToolResult]] | None = field(
        default=None, repr=False, compare=False
    )
    needs_approval: ApprovalState = field(default=False, compare=False)
    approval_display: Callable[[], str] | None = field(
        default=None, repr=False, compare=False
    )
    show_output: bool = field(default=False, compare=False)
    truncation_allowed: bool = field(default=True, compare=False)


# ---------------------------------------------------------------------------
# Param — description metadata carried in Annotated[type, Param(...)]
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Param:
    """Attach a description (and optional enum) to a tool parameter.

    Example::

        path: Annotated[str, Param("Absolute path to the file")]
        direction: Annotated[str, Param("Direction", enum=["north", "south"])]
    """

    description: str
    enum: list[str] | None = None


# ---------------------------------------------------------------------------
# Tool base class
# ---------------------------------------------------------------------------

class Tool:
    """
    Describes a callable tool the LLM may invoke.

    Subclass this or use the :func:`tool` decorator (which does so
    automatically).  The class attributes define the JSON schema sent to the
    LLM; :meth:`execute` performs the actual work.

    Hooks
    -----
    Two optional hooks can be attached to any ``Tool`` instance to intercept
    execution without modifying the underlying function.  Both are plain
    callables (sync or async); the framework awaits them if they return a
    coroutine.

    ``pre_execute_hook(arguments: dict[str, Any]) -> dict[str, Any]``
        Called with the raw keyword-argument dict *before* the tool function
        is invoked.  Must return the (possibly modified) arguments dict that
        will actually be forwarded to the function.  A typical use-case is
        rewriting absolute paths to relative ones so the LLM only ever sees
        project-relative paths.

    ``post_execute_hook(result: ToolResult) -> ToolResult``
        Called with the :class:`ToolResult` *after* the tool function returns
        (and after the result is normalised to a ``ToolResult``).  Must return
        the (possibly modified) ``ToolResult`` that will be sent back to the
        LLM.  A typical use-case is stripping the project-root prefix from
        paths that appear in tool output.

    Example — attach a simple logger::

        def _log_args(args):
            print("calling with", args)
            return args

        def _log_result(result):
            print("got", result.content[:80])
            return result

        my_tool.pre_execute_hook = _log_args
        my_tool.post_execute_hook = _log_result
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}
    required: list[str] = []
    needs_approval: ApprovalState | Callable[[dict[str, Any]], ApprovalState] = False
    show_output: bool = False  # If True, the renderer prints the tool result content

    # If False, this tool's result is exempt from the ``max_tool_output`` cap.
    # For tools whose output is instructions rather than data — a loaded skill,
    # say — a clipped result is worse than useless: the model silently follows
    # half a procedure.  Such output is still redacted wholesale once it ages
    # out of the verbatim window, which is safe because the model can simply
    # load it again.
    truncation_allowed: bool = True

    # Optional intercept hooks — see class docstring.
    pre_execute_hook: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    post_execute_hook: Callable[[ToolResult], ToolResult] | None = None

    def requires_approval(self, arguments: dict[str, Any]) -> ApprovalState:
        """Resolve needs_approval for a specific set of arguments.

        Returns:
            False    — execute immediately
            True     — check whitelist, then ask human if needed
            "human"  — skip whitelist, always ask human
        """
        na = self.__class__.needs_approval
        if callable(na):
            return na(arguments)
        return na  # type: ignore[return-value]

    def approval_display(self, arguments: dict[str, Any]) -> str:
        """Human-readable summary shown when user approval is required."""
        args_str = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
        return f"{self.name}({args_str})"

    def validate_arguments(self, arguments: dict[str, Any]) -> ToolResult | None:
        """Check required args are present. Returns a ToolResult error if invalid, else None."""
        missing = [k for k in self.required if k not in arguments]
        if missing:
            return ToolResult(
                content=(
                    f"Tool '{self.name}' called with missing required arguments: {missing}\n"
                    f"Required: {self.required}\n"
                    f"You passed: {list(arguments.keys())}\n"
                    "Please retry with the correct arguments."
                ),
                is_error=True,
            )
        return None

    async def execute(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Internal helpers for the @tool decorator
# ---------------------------------------------------------------------------

_PY_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _unwrap_annotated(hint: Any) -> tuple[Any, Param | None]:
    if get_origin(hint) is Annotated:
        args = get_args(hint)
        base = args[0]
        meta = next((a for a in args[1:] if isinstance(a, Param)), None)
        return base, meta
    return hint, None


def _json_type(base: Any) -> str:
    return _PY_TO_JSON.get(base, "string")


def _build_tool(
    fn: Callable[..., Any],
    needs_approval: ApprovalState | Callable[[dict[str, Any]], ApprovalState],
    show_output: bool = False,
    truncation_allowed: bool = True,
) -> Tool:
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:  # noqa: BLE001
        hints = {}

    doc = inspect.getdoc(fn) or ""
    description = doc.splitlines()[0].strip() if doc else fn.__name__

    params: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        hint = hints.get(name, str)
        base_type, param_meta = _unwrap_annotated(hint)
        entry: dict[str, Any] = {
            "type": _json_type(base_type),
            "description": param_meta.description if param_meta else "",
        }
        if param_meta and param_meta.enum:
            entry["enum"] = param_meta.enum
        params[name] = entry
        if param.default is inspect.Parameter.empty:
            required.append(name)

    class _FnTool(Tool):
        pass

    _FnTool.name = fn.__name__
    _FnTool.description = description
    _FnTool.parameters = params
    _FnTool.required = required
    _FnTool.needs_approval = needs_approval
    _FnTool.show_output = show_output
    _FnTool.truncation_allowed = truncation_allowed

    async def _execute(self: Tool, **kwargs: Any) -> ToolResult:
        try:
            # ── pre-execute hook ────────────────────────────────────────────
            if self.pre_execute_hook is not None:
                hook_result = self.pre_execute_hook(kwargs)
                if inspect.isawaitable(hook_result):
                    hook_result = await hook_result
                kwargs = hook_result

            if inspect.iscoroutinefunction(fn):
                result = await fn(**kwargs)
            else:
                result = await asyncio.to_thread(fn, **kwargs)
            if isinstance(result, ToolResult):
                tool_result = result
            else:
                tool_result = ToolResult(content=str(result) if result is not None else "")

            # ── post-execute hook ───────────────────────────────────────────
            if self.post_execute_hook is not None:
                hook_result2 = self.post_execute_hook(tool_result)
                if inspect.isawaitable(hook_result2):
                    hook_result2 = await hook_result2
                tool_result = hook_result2

            return tool_result
        except TypeError as exc:  # noqa: BLE001
            # Argument mismatch — give the LLM an actionable correction hint
            expected = list(sig.parameters.keys())
            got = list(kwargs.keys())
            hint = (
                f"Tool call error: {exc}\n"
                f"Tool '{fn.__name__}' expects arguments: {expected}\n"
                f"You passed: {got}\n"
                "Please retry with the correct arguments."
            )
            return ToolResult(content=hint, is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(content=str(exc), is_error=True)

    _FnTool.execute = _execute  # type: ignore[method-assign]
    _FnTool.__name__ = fn.__name__
    return _FnTool()


# ---------------------------------------------------------------------------
# Public decorator
# ---------------------------------------------------------------------------

def tool(
    fn: Callable[..., Any] | None = None,
    *,
    needs_approval: ApprovalState | Callable[[dict[str, Any]], ApprovalState] = False,
    show_output: bool = False,
    truncation_allowed: bool = True,
) -> Any:
    """
    Decorator that turns a function into a :class:`Tool`.

    Can be used bare or with keyword arguments::

        @tool
        def my_tool(x: Annotated[str, Param("The input")]) -> str:
            '''Short description.'''
            ...

        @tool(needs_approval=True)
        async def risky(path: Annotated[str, Param("Path")]) -> str:
            '''Dangerous operation.'''
            ...

        @tool(needs_approval=lambda args: not args["path"].startswith("/safe"))
        def conditional(path: Annotated[str, Param("Path")]) -> str:
            '''Approval only when outside safe dir.'''
            ...
    """
    if fn is not None:
        return _build_tool(fn, needs_approval=False, show_output=False)

    def _decorator(f: Callable[..., Any]) -> Tool:
        return _build_tool(
            f,
            needs_approval=needs_approval,
            show_output=show_output,
            truncation_allowed=truncation_allowed,
        )

    return _decorator
