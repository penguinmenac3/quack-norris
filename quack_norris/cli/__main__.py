"""QuackNorris CLI entry point.

Usage:
    quack-norris                             # interactive REPL (session menu)
    quack-norris --resume <id>               # resume specific session
    quack-norris --prompt "..."              # non-interactive, one prompt
    quack-norris --prompt-file <file>        # non-interactive, prompt from file
    quack-norris chat [...]                  # 'chat' subcommand is an optional alias

TODO (not yet implemented):
- TCP socket server for Web UI relay (cli/socket_server.py)
- Pattern-picker approval UI (whitelist rules)
- Agent definition loading from .agent.md files (hardcoded system prompt for now)
- quack tool (ask-user, agent handover, skill loading, project switching)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from quack_norris.cli.approval import auto_deny_async, interactive_approval
from quack_norris.cli.compaction import compact_history, reconstruct_tail
from quack_norris.cli.renderer import Renderer
from quack_norris.cli.session import (
    SessionMeta,
    append_event,
    archive_session,
    create_session,
    list_sessions,
    new_session_id,
    read_events,
    read_meta,
    remove_streaming_events,
    session_exists,
    touch_meta,
    write_meta,
)
from quack_norris.core.agent import AgentOutput, agent
from quack_norris.core.llm import (
    LLM,
    AssistantMessage,
    ChatMessage,
    UserMessage,
)
from quack_norris.tools.files import make_file_tools
from quack_norris.tools.shell import make_shell_tool
from quack_norris.tools.quack import QuackContext, make_quack_tools
from quack_norris.tools.background import ProcessRegistry
from quack_norris.tools.background_tools import make_background_tools

_DEFAULT_SYSTEM_PROMPT = """\
You are Quack Norris, a helpful AI assistant with access to tools.
You can run shell commands and edit files to help the user with their tasks.
Always be concise and accurate. When you run tools, explain what you are doing.

## Project Context

**Your very first action in every session must be to look for `AGENTS.md` at
the project root and read it using the `file_view` tool. If no `AGENTS.md`
exists, fall back to `CLAUDE.md`. Do this before responding to the user or
taking any other action.** These files contain project-specific conventions,
constraints, and guidance that must be followed throughout the session. If
neither file exists, proceed normally.

## Persisting Learnings

If you discover something during a session that would be valuable to remember
in future sessions — such as a project convention, a non-obvious constraint, a
recurring user preference, or a hard-won debugging insight — you should propose
writing it back to `AGENTS.md` (or `CLAUDE.md` if that is what the project
uses, creating the file if it does not yet exist).

**Before writing anything to these files, always clarify with the user:**
- What you intend to add and why
- Which file you plan to write to
- The exact content you would insert

Only proceed once the user has confirmed. Never silently modify these files.
"""

_DEFAULT_MODEL = "ollama/qwen3:14b"


# ---------------------------------------------------------------------------
# Slash command context
# ---------------------------------------------------------------------------

@dataclass
class SlashContext:
    """Mutable state passed to slash command handlers.

    Slash commands that need to call the LLM or mutate history (e.g.
    ``/compact``) receive this instead of individual arguments.  The REPL
    loop constructs one instance and passes it on every ``_handle_slash``
    call so state changes (model switch, history replacement) are visible
    immediately.
    """

    session_id: str
    meta: SessionMeta
    chat_history: list[ChatMessage]
    model: str
    system_prompt: str
    whitelist: "Whitelist | None" = field(default=None)
    archive_on_exit: bool = field(default=False)
    system_prompt_parts: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="quack-norris",
        description="QuackNorris AI assistant",
    )
    _add_chat_args(parser)
    return parser.parse_args()


def _add_chat_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--resume",
        nargs="?",
        const="",  # --resume with no value → show session menu
        metavar="ID",
        help="Resume a session. Without ID: show session picker. With ID: resume directly.",
    )
    p.add_argument("--prompt", metavar="TEXT", help="Send one prompt (non-interactive)")
    p.add_argument("--prompt-file", metavar="FILE", help="Send file contents as prompt (non-interactive)")
    p.add_argument("--model", metavar="MODEL", help="Override model (group/name)")
    p.add_argument("--agent", metavar="NAME", help="Agent name (TODO: .agent.md loading)")
    p.add_argument("--project", metavar="PROJECT", help="Start in a specific project (short name or absolute path)")
    p.add_argument("--config", metavar="FILE", help="Path to llms.yaml / config.yaml")
    p.add_argument(
        "--archive-on-exit",
        action="store_true",
        default=False,
        help="Archive the session on exit (useful for throwaway test sessions)",
    )


# ---------------------------------------------------------------------------
# History reconstruction from session.jsonl
# ---------------------------------------------------------------------------

def _build_chat_history(session_id: str) -> list[ChatMessage]:
    """Reconstruct LLM chat history from the event log.

    Handles history_compacted: if present, uses the summary as a system-role
    UserMessage prefix and only includes events after cutoff_id.
    """
    events = read_events(session_id)
    if not events:
        return []

    # Find most recent history_compacted event
    compaction = None
    for ev in reversed(events):
        if ev.get("type") == "history_compacted":
            compaction = ev
            break

    cutoff_id = compaction["data"]["cutoff_id"] if compaction else -1
    summary = compaction["data"]["summary"] if compaction else None

    history: list[ChatMessage] = []
    if summary:
        history.append(UserMessage(content=f"[Previous conversation summary]: {summary}"))
    history.extend(reconstruct_tail(events, cutoff_id))
    return history


# ---------------------------------------------------------------------------
# Event logging helpers (wrap append_event + touch_meta)
# ---------------------------------------------------------------------------

def _log_user_message(session_id: str, meta: SessionMeta, text: str) -> str:
    message_id = f"m_{uuid.uuid4().hex[:8]}"
    # Sanitize lone surrogate characters that Windows paste can introduce,
    # which would otherwise crash UTF-8 encoding (UnicodeEncodeError: surrogates not allowed).
    text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    if not session_exists(session_id):
        create_session(meta)  # lazy: create dir on first message
    append_event(session_id, "user_message", {"message_id": message_id, "text": text})
    touch_meta(meta, status="working")
    return message_id


def _log_system_hint(session_id: str, text: str) -> None:
    append_event(session_id, "system_hint", {"text": text})


def _log_content_start(session_id: str, message_id: str) -> None:
    append_event(session_id, "content_start", {"message_id": message_id})


def _log_content_delta(session_id: str, message_id: str, text: str) -> None:
    append_event(session_id, "content_delta", {"message_id": message_id, "text": text})


def _log_content_end(session_id: str, message_id: str, text: str) -> None:
    max_removed_id = remove_streaming_events(session_id, message_id)
    append_event(session_id, "content_end", {"message_id": message_id, "text": text}, min_id=max_removed_id)


def _log_tool_call_start(session_id: str, call_id: str, tool_name: str, arguments: dict) -> None:
    append_event(session_id, "tool_call_start", {
        "call_id": call_id,
        "tool": tool_name,
        "arguments": arguments,
        "needs_approval": True,
    })


def _log_tool_call_approved(session_id: str, call_id: str) -> None:
    append_event(session_id, "tool_call_approved", {"call_id": call_id})


def _log_tool_call_denied(session_id: str, call_id: str) -> None:
    append_event(session_id, "tool_call_denied", {"call_id": call_id, "auto": False})


def _log_tool_call_result(
    session_id: str, call_id: str, tool_name: str, result_text: str, is_error: bool,
    *, show_output: bool = False,
) -> None:
    append_event(session_id, "tool_call_result", {
        "call_id": call_id,
        "tool": tool_name,
        "was_approved": True,
        "result": result_text,
        "is_error": is_error,
        "show_output": show_output,
    })


# ---------------------------------------------------------------------------
# Agent turn runner (shared by interactive + non-interactive)
# ---------------------------------------------------------------------------

async def _ask_user_interactive(question: str, choices: list[str]) -> str:
    """Print a question from the agent and wait for user input."""
    print(f"\n  [Agent asks] {question}")
    if choices:
        for i, c in enumerate(choices, 1):
            print(f"    {i}. {c}")
        print("  Enter number or free text:")
    from quack_norris.cli.input import read_single_line
    loop = asyncio.get_running_loop()
    try:
        answer = await loop.run_in_executor(None, lambda: read_single_line("  > "))
    except (EOFError, KeyboardInterrupt):
        answer = ""
    return answer.strip()


async def _ask_user_auto_deny(question: str, choices: list[str]) -> str:
    """Non-interactive: return empty string (agent gets no answer)."""
    print(f"  [ask_user suppressed in non-interactive mode] {question}", file=sys.stderr)
    return ""


async def _maybe_auto_compact(
    chat_history: list[ChatMessage],
    model: str,
    session_id: str,
) -> None:
    """Auto-compact history if it exceeds the token threshold.

    Mutates ``chat_history`` in place.  Reads ``compaction.enabled``,
    ``compaction.threshold``, ``compaction.target``, and
    ``compaction.min_turns`` from the active LLM config (``CompactionConfig``
    defaults if the config file has no ``compaction:`` section).
    """
    cfg = LLM.compaction_config()
    if not cfg.enabled:
        return

    # Estimate token count (~4 chars per token heuristic)
    total_chars = sum(
        len(m.content) for m in chat_history if hasattr(m, "content")
    )
    estimated_tokens = total_chars // 4

    context_window = LLM.get_context_window(model)
    threshold = int(context_window * cfg.threshold)

    if estimated_tokens < threshold:
        return
    if len(chat_history) < cfg.min_turns:
        return

    print("  [Auto-compacting history...]")
    new_history = await compact_history(
        chat_history=chat_history,
        model=model,
        session_id=session_id,
        trigger="auto",
        target_tokens=int(context_window * cfg.target),
    )
    if new_history is not chat_history:
        chat_history[:] = new_history


async def _run_turn(
    *,
    session_id: str,
    meta: SessionMeta,
    text: str,
    chat_history: list[ChatMessage],
    system_prompt: str,
    system_prompt_parts: list[str],
    model: str,
    renderer: Renderer,
    interactive: bool,
    whitelist: "Whitelist | None" = None,
    registry: "ProcessRegistry | None" = None,
) -> str:
    """Run one agent turn: log events, call agent loop, return final text."""
    # Mutable prompt container — switch_agent can update [0] between LLM calls
    prompt_ref: list[str] = [system_prompt + "".join(system_prompt_parts)]

    quack_ctx = QuackContext(
        session_id=session_id,
        meta=meta,
        system_prompt_parts=system_prompt_parts,
        prompt_ref=prompt_ref,
        ask_user_fn=_ask_user_interactive if interactive else _ask_user_auto_deny,
    )
    get_cwd = lambda: Path(meta.cwd) if meta.cwd else Path.cwd()
    file_tools = make_file_tools(get_cwd)
    bg_tools = make_background_tools(registry) if registry is not None else []
    all_tools = [make_shell_tool(get_cwd, registry)] + file_tools + make_quack_tools(quack_ctx) + bg_tools

    message_id = _log_user_message(session_id, meta, text)
    chat_history.append(UserMessage(content=text))

    response_message_id = f"m_{uuid.uuid4().hex[:8]}"
    _log_content_start(session_id, response_message_id)

    collected_text: list[str] = []
    pending_tool_approval: dict[str, bool] = {}  # call_id → approved

    from quack_norris.core.agent import TextOutput, ThinkingOutput, ToolCallOutput, ToolResultOutput

    async def _on_output(item: AgentOutput) -> None:
        await renderer.on_output(item)

        if isinstance(item, TextOutput):
            collected_text.append(item.text)
            _log_content_delta(session_id, response_message_id, item.text)

        elif isinstance(item, ToolCallOutput):
            _log_tool_call_start(session_id, item.tool_call_id, item.tool_name, item.arguments)

        elif isinstance(item, ToolResultOutput):
            approved = pending_tool_approval.pop(item.tool_call_id, True)
            _log_tool_call_result(
                session_id,
                item.tool_call_id,
                item.tool_name,
                item.result.content,
                item.result.is_error,
                show_output=item.show_output,
            )

    async def _on_approval(call: ToolCallOutput) -> bool:
        from quack_norris.core.llm import ToolResult as _ToolResult
        if not interactive:
            approved = await auto_deny_async(call)
        elif call.needs_approval == "human":
            approved = await interactive_approval(call, whitelist=None)
        else:
            approved = await interactive_approval(call, whitelist)

        # interactive_approval may return a ToolResult (denial with reason)
        # instead of False — unwrap it here for the event log, store it for
        # the agent loop to use as the tool result directly.
        if isinstance(approved, _ToolResult):
            _log_tool_call_denied(session_id, call.tool_call_id)
            pending_tool_approval[call.tool_call_id] = approved  # ToolResult
            return approved  # agent loop handles ToolResult as denial
        if approved:
            _log_tool_call_approved(session_id, call.tool_call_id)
        else:
            _log_tool_call_denied(session_id, call.tool_call_id)
        pending_tool_approval[call.tool_call_id] = approved
        return approved

    await _maybe_auto_compact(chat_history, model, session_id)

    final_text = await agent(
        model=model,
        system_prompt=lambda: prompt_ref[0],
        tools=all_tools,
        chat_history=chat_history,
        on_permission_request=_on_approval,
        on_output=_on_output,
    )

    renderer.finish_turn()
    _log_content_end(session_id, response_message_id, final_text)

    if meta.name is None and session_exists(session_id):
        from quack_norris.cli.naming import generate_session_name
        generated = await generate_session_name(text, final_text, model)
        if generated:
            meta.name = generated
            print(f"  [Session named: {generated}]")

    touch_meta(meta, status="idle")

    return final_text


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------

async def _run_interactive(
    *,
    session_id: str,
    meta: SessionMeta,
    system_prompt: str,
    model: str,
) -> bool:
    """Run the interactive REPL. Returns True if the session should be archived on exit."""
    from quack_norris.cli.whitelist import Whitelist
    whitelist = Whitelist()
    whitelist.load(Path(meta.cwd) if meta.cwd else Path.cwd())

    renderer = Renderer(interactive=True)
    chat_history = _build_chat_history(session_id)
    system_prompt_parts: list[str] = []

    # Session-scoped background process registry — one per REPL session so
    # parallel sessions never share handles.
    registry = ProcessRegistry()

    ctx = SlashContext(
        session_id=session_id,
        meta=meta,
        chat_history=chat_history,
        model=model,
        system_prompt=system_prompt,
        whitelist=whitelist,
        system_prompt_parts=system_prompt_parts,
    )

    print(f"\nQuackNorris  |  session: {session_id[:8]}...  |  agent: {meta.agent}  |  model: {model}")
    if chat_history:
        await _print_history(session_id)
    print('\nType your message, or /help for commands. Ctrl+C to stop agent, twice to exit.\n')

    _ctrlc_count = 0
    _agent_task: asyncio.Task | None = None

    while True:
        try:
            text = await _read_input()
        except EOFError:
            print("\nBye.")
            break
        except KeyboardInterrupt:
            print("\nBye.")
            break

        if not text:
            continue

        # --- Slash commands ---
        if text.startswith("/"):
            changed = await _handle_slash(text, ctx)
            if changed == "exit":
                print("Bye.")
                break
            if isinstance(changed, tuple) and changed[0] == "skill":
                _, hint = changed
                # Inject as UserMessage and run an agent turn immediately
                text = hint
            elif isinstance(changed, tuple):
                _, hint = changed
                chat_history.append(UserMessage(content=hint))
                model = meta.model or model
                ctx.model = model
                system_prompt = _load_system_prompt(
                    meta.agent,
                    Path(meta.cwd) if meta.cwd else None,
                )
                ctx.system_prompt = system_prompt
                continue
            elif changed:
                model = meta.model or model
                ctx.model = model
                continue
            else:
                continue

        # --- Agent turn ---
        touch_meta(meta, status="working")
        try:
            _agent_task = asyncio.create_task(
                _run_turn(
                    session_id=session_id,
                    meta=meta,
                    text=text,
                    chat_history=chat_history,
                    system_prompt=system_prompt,
                    system_prompt_parts=system_prompt_parts,
                    model=model,
                    renderer=renderer,
                    interactive=True,
                    whitelist=whitelist,
                    registry=registry,
                )
            )
            await _agent_task
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            if _agent_task and not _agent_task.done():
                _agent_task.cancel()
                try:
                    await _agent_task
                except asyncio.CancelledError:
                    pass
            print("\nStopped.")
        finally:
            _agent_task = None
            touch_meta(meta, status="idle")

        print()  # blank line before next prompt

    return ctx.archive_on_exit


async def _read_input() -> str:
    """Read one logical user message, returning the text to send to the LLM.

    Delegates to :mod:`quack_norris.cli.input` which handles:
    - ``\\`` line continuation
    - bulk paste detection (echoes ``[pasted N lines]``)
    - image path detection (echoes ``[image: ...]``) — stub until Part 3
    """
    from quack_norris.cli.input import echo_input, read_user_input
    loop = asyncio.get_running_loop()
    ui = await loop.run_in_executor(None, read_user_input)
    echo_input(ui)
    return ui.text


def _compute_usage(ctx: SlashContext) -> None:
    """Print session usage statistics derived from the event log and in-memory history."""
    from datetime import datetime, timezone

    events = read_events(ctx.session_id) if session_exists(ctx.session_id) else []

    # --- Counts from event log ---
    user_msgs = 0
    tool_calls_total = 0
    tool_calls_denied = 0
    tool_counts: dict[str, int] = {}
    compactions_auto = 0
    compactions_manual = 0
    total_chars_in = 0   # user + tool result content sent to LLM
    total_chars_out = 0  # assistant text generated
    today_chars_in = 0
    today_chars_out = 0
    first_ts: str | None = None

    today_date = datetime.now(timezone.utc).date()

    def _is_today(ts: str | None) -> bool:
        if not ts:
            return False
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).date() == today_date
        except ValueError:
            return False


    for ev in events:
        t = ev.get("type", "")
        data = ev.get("data", {})
        ts = ev.get("ts")
        if first_ts is None:
            first_ts = ts
        if t == "user_message":
            user_msgs += 1
            chars = len(data.get("text", ""))
            total_chars_in += chars
            if _is_today(ts):
                today_chars_in += chars
        elif t == "content_end":
            chars = len(data.get("text", ""))
            total_chars_out += chars
            if _is_today(ts):
                today_chars_out += chars
        elif t == "tool_call_start":
            tool_name = data.get("tool", "unknown")
            tool_calls_total += 1
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
        elif t == "tool_call_denied":
            tool_calls_denied += 1
        elif t == "tool_call_result":
            chars = len(data.get("result", ""))  # result fed back to LLM
            total_chars_in += chars
            if _is_today(ts):
                today_chars_in += chars
        elif t == "history_compacted":
            trigger = data.get("trigger", "manual")
            if trigger == "auto":
                compactions_auto += 1
            else:
                compactions_manual += 1

    total_chars = total_chars_in + total_chars_out
    est_total = total_chars // 4
    est_in = total_chars_in // 4
    est_out = total_chars_out // 4
    est_today = (today_chars_in + today_chars_out) // 4

    # --- Active history token estimate ---
    active_chars = sum(
        len(m.content) for m in ctx.chat_history if hasattr(m, "content")
    )
    est_active = active_chars // 4
    context_window = LLM.get_context_window(ctx.model)
    active_pct = est_active * 100 // context_window if context_window else 0

    # --- Session age ---
    age_str = ""
    if first_ts:
        try:
            start = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - start
            h, rem = divmod(int(delta.total_seconds()), 3600)
            m, s = divmod(rem, 60)
            age_str = f"  session age      {h}h {m}m {s}s"
        except ValueError:
            pass

    compaction_str = f"{compactions_auto} auto, {compactions_manual} manual"

    lines = [
        "  ── Usage ──────────────────────────────────────",
        f"  user messages    {user_msgs}",
        f"  tool calls       {tool_calls_total}  ({tool_calls_denied} denied)",
    ]
    if tool_counts:
        for name, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
            lines.append(f"    {name:<18} {count}")
    lines += [
        f"  compactions      {compaction_str}",
        f"  est. tokens used {est_total:,}  (in: {est_in:,}, out: {est_out:,})",
        f"  est. tokens today {est_today:,}  (in: {today_chars_in // 4:,}, out: {today_chars_out // 4:,})",
        f"  active history   ~{est_active:,} tokens  ({active_pct}% of {context_window:,} context window)",
    ]
    if age_str:
        lines.append(age_str)
    lines.append("  ────────────────────────────────────────────────")
    print("\n".join(lines))


async def _handle_slash(text: str, ctx: SlashContext) -> str | bool | tuple[bool, str] | tuple[str, str]:
    """Process a slash command.

    Returns:
      'exit'           — user wants to quit
      False            — no-op (listing, unknown command)
      True             — meta changed, no chat hint needed
      (True, str)      — meta changed, inject str as a UserMessage into chat history
      ('skill', str)   — inject str as a UserMessage and run an agent turn
    """
    parts = text.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    meta = ctx.meta
    session_id = ctx.session_id

    if cmd in ("/exit", "/quit"):
        return "exit"

    if cmd == "/archive":
        ctx.archive_on_exit = True
        print("  Archiving session on exit...")
        return "exit"

    if cmd == "/help":
        print(
            "  /agent <name>      Switch agent immediately\n"
            "  /model <name>      Switch model immediately\n"
            "  /project <dir>     Change project working directory\n"
            "  /skills            List available skills\n"
            "  /<skill_name>      Load a skill into context\n"
            "  /compact           Compact history\n"
            "  /usage             Show session token and request stats\n"
            "  /archive           Exit and archive this session\n"
            "  /help              Show this help\n"
            "  /exit  /quit       Exit"
        )
        return False

    if cmd == "/agent":
        if not arg:
            _list_agents(meta.agent, meta.cwd)
            return False
        from quack_norris.cli.agents import discover_agents
        available = discover_agents(Path(meta.cwd) if meta.cwd else None)
        if arg not in available:
            close = [a for a in available if arg.lower() in a.lower() or a.lower() in arg.lower()]
            print(f"  Agent '{arg}' not found.")
            if close:
                print(f"  Did you mean: {', '.join(close)}")
            else:
                print(f"  Available: {', '.join(available) if available else '(none)'}")
            return False
        old = meta.agent
        meta.agent = arg
        if session_exists(session_id):
            write_meta(meta)
            _log_system_hint(session_id, f"[System: Agent switched to {arg}]")
        print(f"  Agent: {old} → {arg}")
        return True, f"[The user switched the active agent to '{arg}'.]"

    if cmd == "/model":
        if not arg:
            _list_models(meta.model)
            return False
        old = meta.model or "(default)"
        meta.model = arg
        if session_exists(session_id):
            write_meta(meta)
            _log_system_hint(session_id, f"[System: Model switched to {arg}]")
        print(f"  Model: {old} → {arg}")
        return True

    if cmd == "/project":
        if not arg:
            _list_projects(meta.cwd)
            return False
        path = _resolve_project(arg)
        if path is None:
            return False
        old = meta.cwd
        meta.cwd = str(path)
        if session_exists(session_id):
            write_meta(meta)
            _log_system_hint(session_id, f"[System: Project directory changed to {path}]")
        # Reload whitelist so project-scope rules reflect the new project root
        if ctx.whitelist is not None:
            ctx.whitelist.load(path)
        print(f"  Project: {old} → {path}")
        return True, f"[The user switched the project directory to '{path}'. Relative paths now resolve against this directory.]"

    if cmd == "/skills":
        _list_skills(ctx.meta.cwd)
        return False

    if cmd == "/usage":
        _compute_usage(ctx)
        return False

    if cmd == "/compact":
        print("  Compacting history...")
        new_history = await compact_history(
            chat_history=ctx.chat_history,
            model=ctx.model,
            session_id=ctx.session_id,
            trigger="manual",
        )
        if new_history is ctx.chat_history:
            print("  Nothing to compact (history too short).")
        else:
            ctx.chat_history[:] = new_history
            print("  done.")
        return False

    # Try to match as a skill name (/<skill_name>)
    skill_name = cmd[1:]  # strip leading /
    if skill_name:
        from quack_norris.cli.agents import discover_skills, load_skill_content
        available = discover_skills(Path(meta.cwd) if meta.cwd else None)
        if skill_name in available:
            content = load_skill_content(skill_name, Path(meta.cwd) if meta.cwd else None)
            if content is not None:
                hint = f"{text}\n\n[autoloaded skill]\n# Skill: {skill_name}\n\n{content}"
                print(f"  Skill '{skill_name}' loaded.")
                return "skill", hint
        close = [s for s in available if skill_name.lower() in s.lower() or s.lower() in skill_name.lower()]
        print(f"  Unknown command or skill: {cmd}.")
        if close:
            print(f"  Did you mean skill: {', '.join(close)}?")
        else:
            print("  Type /help for commands or /skills to list skills.")
        return False

    print(f"  Unknown command: {cmd}. Type /help for commands.")
    return False


# ---------------------------------------------------------------------------
# Session selection menu
# ---------------------------------------------------------------------------

def _session_menu(initial_meta: SessionMeta) -> tuple[str, SessionMeta]:
    """Show session selection menu. Returns (session_id, meta)."""
    sessions = list_sessions()
    print("\nQuackNorris\n")
    print("  [0] New session")
    for i, s in enumerate(sessions, 1):
        status = s.status.ljust(7)
        from datetime import datetime, timezone
        try:
            last = datetime.fromisoformat(s.last_active.replace("Z", "+00:00"))
            age = _human_age(last)
        except Exception:  # noqa: BLE001
            age = "?"
        name = s.name or s.id[:8] + "..."
        print(f"  [{i}] {name:<30} ({status}, {age})")

    print()
    while True:
        try:
            choice = input("Select: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

        if choice == "0" or choice == "":
            sid = new_session_id()
            meta = initial_meta
            meta.id = sid
            return sid, meta

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                s = sessions[idx]
                return s.id, s
        except ValueError:
            pass
        print("  Invalid selection.")


def _human_age(dt) -> str:  # noqa: ANN001
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    diff = now - dt
    secs = int(diff.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


# ---------------------------------------------------------------------------
# Non-interactive mode
# ---------------------------------------------------------------------------

async def _run_non_interactive(
    *,
    prompt: str,
    model: str,
    system_prompt: str,
) -> None:
    """Send one prompt, stream response to stdout, exit."""
    # Ephemeral session — not saved to disk
    session_id = new_session_id()
    meta = SessionMeta(id=session_id, model=model, owner=None)
    chat_history: list[ChatMessage] = []
    renderer = Renderer(interactive=False)
    registry = ProcessRegistry()

    await _run_turn(
        session_id=session_id,
        meta=meta,
        text=prompt,
        chat_history=chat_history,
        system_prompt=system_prompt,
        system_prompt_parts=[],
        model=model,
        renderer=renderer,
        interactive=False,
        registry=registry,
    )


# ---------------------------------------------------------------------------
# System prompt loading
# ---------------------------------------------------------------------------

_DEFAULT_AGENT_NAME = "Quack Norris"

def _load_system_prompt(agent_name: str | None, project_root: Path | None = None) -> str:
    """Load system prompt from agent definition, or return the default."""
    from quack_norris.cli.agents import load_agent_system_prompt
    if agent_name and agent_name != _DEFAULT_AGENT_NAME:
        return load_agent_system_prompt(agent_name, project_root)
    return _DEFAULT_SYSTEM_PROMPT


# LLM setup
# ---------------------------------------------------------------------------

def _setup_llm(config_path: str | None) -> None:
    """Load LLM config. ``LLM.setup()`` merges the project-local config (cwd,
    or *config_path* if given) on top of the global ``~/.quack-norris/`` one.
    """
    try:
        LLM.setup(config_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print(
            "Create config.yaml or llms.yaml in the current directory or in "
            "~/.quack-norris/, or pass --config <path>.",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    _setup_llm(getattr(args, "config", None))

    # Determine model: CLI flag > config defaults.model > hardcoded fallback
    model = getattr(args, "model", None) or LLM.default_model() or _DEFAULT_MODEL

    # Resolve --project flag to a CWD path
    project_arg = getattr(args, "project", None)
    initial_cwd: str | None = None
    if project_arg:
        resolved = _resolve_project(project_arg)
        if resolved is None:
            sys.exit(1)
        initial_cwd = str(resolved)

    # Load system prompt from agent definition if specified
    agent_name = getattr(args, "agent", None)
    system_prompt = _load_system_prompt(agent_name, Path(initial_cwd) if initial_cwd else None)

    # Non-interactive mode
    prompt_text: str | None = None
    if getattr(args, "prompt", None):
        prompt_text = args.prompt
    elif getattr(args, "prompt_file", None):
        path = Path(args.prompt_file)
        if not path.exists():
            print(f"Error: prompt file not found: {path}", file=sys.stderr)
            sys.exit(1)
        prompt_text = path.read_text(encoding="utf-8")

    if prompt_text is not None:
        try:
            asyncio.run(_run_non_interactive(
                prompt=prompt_text,
                model=model,
                system_prompt=system_prompt,
            ))
        except KeyboardInterrupt:
            pass
        return

    # Interactive mode
    resume_arg = getattr(args, "resume", None)  # None | "" | "<id>"

    initial_meta = SessionMeta(
        id="",
        model=model if getattr(args, "model", None) else None,
        cwd=initial_cwd or str(Path.cwd()),
        owner="terminal",
        pid=os.getpid(),
    )

    if resume_arg is None:
        # Plain `quack-norris` — start a new session immediately, no menu
        session_id = new_session_id()
        initial_meta.id = session_id
        meta = initial_meta
    elif resume_arg == "":
        # `quack-norris --resume` (no id) — show session picker
        session_id, meta = _session_menu(initial_meta)
    else:
        # `quack-norris --resume <id>` — exact match, then prefix match
        meta = read_meta(resume_arg)
        if meta is not None:
            session_id = resume_arg
        else:
            matches = [s for s in list_sessions(include_archived=True) if s.id.startswith(resume_arg)]
            if len(matches) == 1:
                session_id = matches[0].id
                meta = matches[0]
            else:
                if len(matches) == 0:
                    print(f"No session matching '{resume_arg}', select from list:")
                else:
                    print(f"Ambiguous prefix '{resume_arg}' matches {len(matches)} sessions, select from list:")
                session_id, meta = _session_menu(initial_meta)

    meta.owner = "terminal"
    meta.pid = os.getpid()
    if session_exists(session_id):
        # Resuming an existing session — update meta immediately
        write_meta(meta)
    # New sessions: directory created lazily on first user message

    effective_model = meta.model or model
    # For interactive sessions, prefer meta.agent (persisted) over --agent flag
    effective_system_prompt = _load_system_prompt(
        meta.agent or agent_name,
        Path(meta.cwd) if meta.cwd else None,
    )

    try:
        archive_from_slash = asyncio.run(_run_interactive(
            session_id=session_id,
            meta=meta,
            system_prompt=effective_system_prompt,
            model=effective_model,
        ))
    except KeyboardInterrupt:
        archive_from_slash = False

    # Clean up / archive on exit
    archive = getattr(args, "archive_on_exit", False) or archive_from_slash
    if not session_exists(session_id):
        pass  # session was never used — nothing to clean up, nothing to print
    elif archive:
        archive_session(session_id)
        print("\nSession archived.")
    else:
        meta.pid = None
        meta.port = None
        meta.owner = None
        meta.status = "idle"
        write_meta(meta)
        print(f"\nTo resume this session:\n  quack-norris --resume {session_id}")


# ---------------------------------------------------------------------------
# Slash command helpers: list available options
# ---------------------------------------------------------------------------

def _list_models(current: str | None) -> None:
    current_str = current or "(default)"
    print(f"  Current model: {current_str}")
    configs = LLM.configs()
    if not configs:
        print("  No models configured.")
        return
    print("  Available models:")
    for cfg in configs:
        if cfg.models:
            for m in cfg.models:
                marker = "*" if f"{cfg.group}/{m}" == current else " "
                print(f"   {marker} {cfg.group}/{m}")
        elif cfg.provider != "AWSBedrock":
            # Fetch live model list from OpenAI-compatible /v1/models endpoint
            models = _fetch_models_sync(cfg.api_endpoint, cfg.api_key)
            if models:
                for m in models:
                    marker = "*" if f"{cfg.group}/{m}" == current else " "
                    print(f"   {marker} {cfg.group}/{m}")
            else:
                marker = "*" if current and current.startswith(cfg.group + "/") else " "
                print(f"   {marker} {cfg.group}/<model>  (could not fetch model list)")
        else:
            marker = "*" if current and current.startswith(cfg.group + "/") else " "
            print(f"   {marker} {cfg.group}/<model>  (Bedrock — no static list)")
    print("  Usage: /model <group>/<model>")


def _fetch_models_sync(api_endpoint: str, api_key: str | None) -> list[str]:
    """Fetch model names from GET /v1/models synchronously. Returns [] on any error."""
    try:
        import urllib.request
        import urllib.error
        url = api_endpoint.rstrip("/").removesuffix("/v1") + "/v1/models"
        req = urllib.request.Request(url)
        if api_key and api_key not in ("unused", "ollama"):
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=4) as resp:
            import json as _json
            data = _json.loads(resp.read().decode())
        return sorted(m["id"] for m in data.get("data", []) if "id" in m)
    except Exception:  # noqa: BLE001
        return []


def _list_agents(current: str, cwd: str | None = None) -> None:
    from quack_norris.cli.agents import discover_agents
    print(f"  Current agent: {current}")
    agents = discover_agents(Path(cwd) if cwd else None)
    if agents:
        print("  Available agents:")
        for a in agents:
            marker = " (active)" if a == current else ""
            print(f"    {a}{marker}")
    else:
        print("  No agent definitions found. Install agents with quack-norris-manage.")


def _list_skills(cwd: str | None = None) -> None:
    from quack_norris.cli.agents import discover_skills
    skills = discover_skills(Path(cwd) if cwd else None)
    if skills:
        print("  Available skills:")
        for s in skills:
            print(f"    /{s}")
    else:
        print("  No skills found. Install skills with quack-norris-manage.")


_PROJECT_MARKERS = {".git", ".github", ".agents", ".venv", "node_modules", "pyproject.toml", "package.json"}


def _find_projects(roots: list[Path], max_depth: int = 3) -> list[Path]:
    """Walk roots up to max_depth and return dirs that contain a project marker.

    Always recurses into all non-hidden subdirectories so nested projects
    (e.g. ~/Code/Quack-Norris/quack-norris-3.0) are found even if a parent
    also has a marker.
    """
    found: list[Path] = []
    seen: set[Path] = set()

    def _walk(d: Path, depth: int) -> None:
        if depth == 0 or d in seen:
            return
        seen.add(d)
        try:
            children = sorted(d.iterdir())
        except PermissionError:
            return
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if any((child / m).exists() for m in _PROJECT_MARKERS):
                if child not in seen:
                    found.append(child)
                    seen.add(child)
            _walk(child, depth - 1)

    for root in roots:
        _walk(root, max_depth)
    return found


def _short_project_names(projects: list[Path]) -> dict[Path, str]:
    """Build shortest unique suffix names for each project path.

    E.g. two projects sharing the same folder name get parent/name,
    unique ones just get name.
    """
    # Start with just the project name (last part)
    names: dict[Path, list[str]] = {p: [p.name] for p in projects}

    def _key(p: Path) -> str:
        return "/".join(names[p])

    # Iteratively add parent segments until all names are unique
    for _ in range(10):
        seen: dict[str, list[Path]] = {}
        for p in projects:
            seen.setdefault(_key(p), []).append(p)
        conflicts = [paths for paths in seen.values() if len(paths) > 1]
        if not conflicts:
            break
        for paths in conflicts:
            for p in paths:
                parent_part = names[p][-1]  # last prepended part so far
                # Prepend next parent segment
                current_parts = names[p]
                # figure out how many parts deep we are
                depth = len(current_parts)
                ancestor = p
                for _ in range(depth):
                    ancestor = ancestor.parent
                if ancestor != ancestor.parent:  # not filesystem root
                    names[p] = [ancestor.name] + current_parts

    return {p: _key(p) for p in projects}


def _resolve_project(arg: str) -> Path | None:
    """Resolve a partial project name to a full path.

    Accepts:
      - exact full path
      - short name or partial suffix like 'mcp2cli' or 'Agents/mcp2cli'
    Returns None if not found or ambiguous (prints reason).
    """
    # Try as a literal path first
    literal = Path(arg).expanduser()
    if literal.is_absolute() and literal.exists():
        return literal

    projects = _find_projects([Path.home()])
    short_names = _short_project_names(projects)

    # Normalise separator
    needle = arg.replace("\\", "/").lower()

    # Match: project's full path suffix must end with the needle (case-insensitive)
    matches = [
        p for p in projects
        if str(p).replace("\\", "/").lower().endswith(needle)
    ]

    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        print(f"  No project matching '{arg}' found. Use /project to list available projects.")
        return None
    # Ambiguous — show options
    print(f"  '{arg}' is ambiguous, matches:")
    for m in matches:
        print(f"    {short_names[m]}  ({m})")
    print("  Add more path components to disambiguate.")
    return None


def _list_projects(current_cwd: str | None) -> None:
    current = Path(current_cwd).resolve() if current_cwd else Path.cwd()
    projects = _find_projects([Path.home()])
    short_names = _short_project_names(projects)
    print(f"  Current project: {current_cwd}")
    if projects:
        print("  Detected projects:")
        for p in projects[:30]:
            marker = " (active)" if p.resolve() == current else ""
            print(f"    {short_names[p]}  ({p}){marker}")
        if len(projects) > 30:
            print(f"    ... ({len(projects) - 30} more)")
    else:
        print("  No projects found under home directory.")
    print("  Usage: /project <name>  (use short name; full path also accepted)")


# ---------------------------------------------------------------------------
# History replay for terminal on resume
# ---------------------------------------------------------------------------

async def _print_history(session_id: str) -> None:
    """Print conversation history to the terminal when resuming a session.

    Uses the same ``Renderer`` that is used for live output so the formatting
    is identical — tool calls get the ``⚡`` badge with indented arguments,
    errors get the ``❌`` badge, and assistant text is shown verbatim.
    """
    from quack_norris.core.agent import TextOutput, ToolCallOutput, ToolResultOutput
    from quack_norris.core.llm import ToolResult

    events = read_events(session_id)
    if not events:
        return

    # Find compaction cutoff
    cutoff_id = -1
    summary = None
    for ev in reversed(events):
        if ev.get("type") == "history_compacted":
            cutoff_id = ev["data"]["cutoff_id"]
            summary = ev["data"]["summary"]
            break

    renderer = Renderer(interactive=True)

    print("\n" + "─" * 60)
    if summary:
        print(f"[Compacted history summary]\n{summary}")
        print("─" * 60)

    # We need to match tool_call_start events to their tool_call_result so we
    # can decide whether to show tool output.  Build a lookup by call_id.
    tool_call_map: dict[str, dict] = {}  # call_id → tool_call_start data
    for ev in events:
        if ev.get("type") == "tool_call_start":
            call_id = ev["data"].get("call_id", "")
            tool_call_map[call_id] = ev["data"]

    for ev in events:
        if ev["id"] <= cutoff_id:
            continue
        t = ev.get("type")
        data = ev.get("data", {})

        if t == "user_message":
            renderer.finish_turn()
            print(f"\n> {data.get('text', '')}")

        elif t == "content_end":
            # Replay the full assistant text through the renderer so it goes
            # through the same state-machine (handles _after_tool spacing etc.)
            text = data.get("text", "")
            if text:
                await renderer.on_output(TextOutput(text=text))
            renderer.finish_turn()

        elif t == "tool_call_start":
            call_id = data.get("call_id", "")
            tool_name = data.get("tool", "")
            arguments = data.get("arguments", {})
            # Always render as auto-approved (needs_approval=False) — the
            # decision was already made; we just want the ⚡ display.
            await renderer.on_output(ToolCallOutput(
                tool_call_id=call_id,
                tool_name=tool_name,
                arguments=arguments,
                needs_approval=False,
            ))

        elif t == "tool_call_result":
            call_id = data.get("call_id", "")
            tool_name = data.get("tool", "")
            result_text = data.get("result", "")
            is_error = data.get("is_error", False)
            # Use the stored show_output flag (logged at event time from
            # ToolResultOutput.show_output, which mirrors Tool.show_output).
            # Falls back to False so file_view etc. stay silent, as live.
            show_output = data.get("show_output", False)
            await renderer.on_output(ToolResultOutput(
                tool_call_id=call_id,
                tool_name=tool_name,
                result=ToolResult(content=result_text, is_error=is_error),
                show_output=show_output,
            ))

        elif t == "system_hint":
            renderer.finish_turn()
            print(f"  [{data.get('text', '')}]")

    renderer.finish_turn()
    print("─" * 60)
    print("(session resumed — continuing above)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
