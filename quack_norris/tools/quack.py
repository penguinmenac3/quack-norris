"""Quack runtime tools.

These tools reach into the CLI/session runtime. They are built via
``make_quack_tools(context)`` so they can read and mutate session state.

Flat tool set (no subcommands):

Auto-approved:
  ask_user          — ask the user a question and wait for input
  list_agents       — list available agents
  list_skills       — list available skills
  list_projects     — list known project directories

Requires approval:
  switch_agent      — hand the session to a different agent
  spawn_subagent    — run a sub-task with a different agent, return result
  use_skill         — load a skill and return its content
  switch_project    — change the session working directory
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from quack_norris.core.llm import Param, ToolResult, tool


# ---------------------------------------------------------------------------
# Runtime context (mutable, injected per-session)
# ---------------------------------------------------------------------------

@dataclass
class QuackContext:
    """Mutable session state accessible to quack tools."""

    session_id: str
    meta: Any                        # SessionMeta — avoid circular import
    system_prompt_parts: list[str]   # extra parts appended to base system prompt
    prompt_ref: list[str]            # single-element list; [0] is the live system prompt
    ask_user_fn: Any                 # async (question: str, choices: list[str]) -> str
    on_project_switch: Any | None = None  # async (path: str) -> None  (deferred)


# ---------------------------------------------------------------------------
# Factory — returns a list[Tool] with context captured in closures
# ---------------------------------------------------------------------------

def make_quack_tools(ctx: QuackContext) -> list:
    """Return quack tool instances bound to the given session context."""

    # ------------------------------------------------------------------
    # ask_user
    # ------------------------------------------------------------------

    @tool
    async def ask_user(
        question: Annotated[str, Param("The question to ask the user")],
        choices: Annotated[str, Param(
            "Optional comma-separated list of choices to present, e.g. 'Refactor,Fix in place,Skip'"
        )] = "",
    ) -> ToolResult:
        """Ask the user a question and return their answer. No approval needed."""
        choice_list = [c.strip() for c in choices.split(",") if c.strip()] if choices else []
        answer = await ctx.ask_user_fn(question, choice_list)
        return ToolResult(content=answer)

    # ------------------------------------------------------------------
    # list_agents
    # ------------------------------------------------------------------

    @tool
    def list_agents() -> ToolResult:
        """List available agents. Only call this when the user explicitly asks to switch agent or wants to know which agents are available. Do not call proactively."""
        from quack_norris.cli.agents import discover_agents
        agents = discover_agents(Path(ctx.meta.cwd) if ctx.meta.cwd else None)
        if not agents:
            return ToolResult(content="No agent definitions found. Default agent: Quack Norris")
        lines = [f"  {a}" for a in sorted(agents)]
        return ToolResult(content="Available agents:\n" + "\n".join(lines))

    # ------------------------------------------------------------------
    # list_projects
    # ------------------------------------------------------------------

    @tool
    def list_projects() -> ToolResult:
        """List known project directories (identified by .git, .github, .agents, pyproject.toml, etc.). Only call this when the user explicitly asks to switch project or wants to know which projects are available. Do not call proactively."""
        from quack_norris.cli.__main__ import _find_projects, _short_project_names
        current = ctx.meta.cwd or str(Path.cwd())
        current_name = Path(current).name or current
        projects = _find_projects([Path.home()])
        if not projects:
            return ToolResult(content=f"Current project: {current_name} ({current})\nNo projects found under home directory.")
        short_names = _short_project_names(projects)
        lines = [f"  {short_names[p]}  ({p})" for p in projects[:30]]
        result = f"Current project: {current_name} ({current})\nDetected projects (use short name with switch_project):\n" + "\n".join(lines)
        if len(projects) > 30:
            result += f"\n  ... ({len(projects) - 30} more)"
        return ToolResult(content=result)

    # ------------------------------------------------------------------
    # switch_agent (approval required)
    # ------------------------------------------------------------------

    @tool(needs_approval=True)
    async def switch_agent(
        name: Annotated[str, Param("Agent name to switch to (use list_agents to see options)")],
    ) -> ToolResult:
        """Switch the current session to a different agent definition.

        Takes effect immediately before the next LLM call in this turn.
        """
        from quack_norris.cli.agents import load_agent_system_prompt
        from quack_norris.cli.session import write_meta, append_event
        ctx.meta.agent = name
        write_meta(ctx.meta)
        new_prompt = load_agent_system_prompt(name, Path(ctx.meta.cwd) if ctx.meta.cwd else None)
        ctx.prompt_ref[0] = new_prompt + "".join(ctx.system_prompt_parts)
        append_event(ctx.session_id, "system_hint", {"text": f"Agent switched to {name}"})
        return ToolResult(content=f"Switched to agent '{name}'. New system prompt is active for the next LLM call.")

    # ------------------------------------------------------------------
    # spawn_subagent (approval required)
    # ------------------------------------------------------------------

    @tool(needs_approval=True)
    async def spawn_subagent(
        agent_name: Annotated[str, Param("Agent name to use for the sub-task (use list_agents to see options)")],
        task: Annotated[str, Param("Description of the sub-task to perform")],
    ) -> ToolResult:
        """Spawn a subagent to handle a specific task and return the result.

        Runs a fresh agent session with the named agent, blocks until done, and
        returns the final response. The current session is not affected.
        The subagent has access to all tools except agent management tools.
        """
        from quack_norris.cli.agents import load_agent_system_prompt
        from quack_norris.core.agent import agent as run_agent
        from quack_norris.core.llm import LLM, UserMessage
        from quack_norris.cli.approval import auto_deny_async
        from quack_norris.tools import shell
        from quack_norris.tools.files import make_file_tools

        sub_prompt = load_agent_system_prompt(agent_name, Path(ctx.meta.cwd) if ctx.meta.cwd else None)
        model = ctx.meta.model or LLM.default_model() or ""
        history = [UserMessage(content=task)]
        collected: list[str] = []

        # Subagent gets static tools + non-agent quack tools (ask_user, skills, projects)
        sub_quack_ctx = QuackContext(
            session_id=ctx.session_id,
            meta=ctx.meta,
            system_prompt_parts=[],
            prompt_ref=[sub_prompt],
            ask_user_fn=ctx.ask_user_fn,
        )
        sub_file_tools = make_file_tools(lambda: Path(ctx.meta.cwd) if ctx.meta.cwd else Path.cwd())
        sub_static = [shell] + sub_file_tools
        sub_quack = make_quack_tools(sub_quack_ctx)
        # Exclude agent-management tools from subagent
        _agent_tools = {"switch_agent", "spawn_subagent"}
        sub_tools = sub_static + [t for t in sub_quack if t.name not in _agent_tools]

        async def _noop_output(item: Any) -> None:
            from quack_norris.core.agent import TextOutput
            if isinstance(item, TextOutput):
                collected.append(item.text)

        from quack_norris.cli.context import build_context_policy

        result = await run_agent(
            model=model,
            system_prompt=sub_prompt,
            tools=sub_tools,
            chat_history=history,
            on_permission_request=auto_deny_async,
            on_output=_noop_output,
            # A subagent's history is throwaway, so it is never persisted and
            # never checkpoint-replayed — but it still has to fit the window.
            context=build_context_policy(model),
        )
        return ToolResult(content=result or "".join(collected))

    # ------------------------------------------------------------------
    # use_skill (no approval)
    # ------------------------------------------------------------------

    # Skill instructions must arrive whole — half a procedure is worse than
    # none, and the model has no way to tell it is following a clipped one.
    @tool(truncation_allowed=False)
    def use_skill(
        name: Annotated[str, Param("Skill name to load (use list_skills to see options)")],
    ) -> ToolResult:
        """Load a skill and return its instructions in the tool result."""
        from quack_norris.cli.agents import find_skill_path, load_skill_content
        project_root = Path(ctx.meta.cwd) if ctx.meta.cwd else None
        skill_path = find_skill_path(name, project_root)
        content = load_skill_content(name, project_root)
        if skill_path is None or content is None:
            return ToolResult(
                content=f"Skill '{name}' not found. Use list_skills to see available skills.",
                is_error=True,
            )
        return ToolResult(
            content=f"# Skill: {name}\n\nSkill-Path: {skill_path}\n\n{content}"
        )

    # ------------------------------------------------------------------
    # switch_project (approval required)
    # ------------------------------------------------------------------

    @tool(needs_approval=True)
    async def switch_project(
        path: Annotated[str, Param("Project name (from list_projects, e.g. 'mcp2cli' or 'Agents/mcp2cli') OR an absolute path to any folder to use as the project root.")],
    ) -> ToolResult:
        """Change the session working directory to a different project."""
        from quack_norris.cli.__main__ import _resolve_project
        resolved = _resolve_project(path)
        if resolved is None:
            return ToolResult(content=f"Project '{path}' not found or ambiguous. Use list_projects to see available projects.", is_error=True)
        p = resolved
        if not p.exists() or not p.is_dir():
            return ToolResult(content=f"Directory not found: {p}", is_error=True)
        ctx.meta.cwd = str(p.resolve())
        from quack_norris.cli.session import write_meta, append_event
        write_meta(ctx.meta)
        append_event(ctx.session_id, "system_hint", {
            "text": f"Project switched to {ctx.meta.cwd}"
        })
        if ctx.on_project_switch is not None:
            await ctx.on_project_switch(ctx.meta.cwd)
        return ToolResult(content=f"Project switched to {ctx.meta.cwd}")

    tools = [
        ask_user,
        list_agents,
        list_projects,
        switch_agent,
        spawn_subagent,
        use_skill,
        switch_project,
    ]

    # Normalise any project-root absolute paths in tool output so the LLM
    # always sees clean relative paths.
    from quack_norris.tools.files import attach_path_normalizer
    attach_path_normalizer(tools, lambda: Path(ctx.meta.cwd) if ctx.meta.cwd else Path.cwd())

    return tools
