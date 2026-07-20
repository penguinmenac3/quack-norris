"""LLM-based auto-approver for tool calls.

Provides an ``on_permission_request`` implementation that asks an LLM to
judge whether a tool call is safe to execute, instead of blocking on user
input.  Intended for non-interactive / CI use cases.

Usage::

    from quack_norris.core.approver import llm_approver
    from quack_norris.core.agent import agent

    approve = llm_approver(
        model="ollama/granite4:tiny-h",
        context="AcmeCorp internal development assistant. Internal projects include Nighthawk and Falcon.",
    )

    await agent(
        ...
        on_permission_request=approve,
    )
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from quack_norris.core.agent import ToolCallOutput
from quack_norris.core.llm import (
    LLM,
    AssistantMessage,
    TextDelta,
    UserMessage,
)

_log = logging.getLogger(__name__)

_SYSTEM_PROMPT_BASE = """\
You are a security-conscious tool-call approver.
An AI agent has requested permission to execute a tool call.
Your job is to decide whether the call is safe to allow.

Respond with a JSON object on a single line using one of these three verdicts:
{{"decision": "approved", "reason": "<short explanation>"}}
{{"decision": "denied",   "reason": "<short explanation>"}}
{{"decision": "human",    "reason": "<short explanation>"}}

Use "human" when you cannot confidently approve or deny — for example when a search
query or data transfer might contain internal information but you are not certain.

Guidelines — APPROVE:
- Read-only operations within the working directory (file reads, git status, listing, grep, etc.)
- Writing or creating source files, config files, or docs within the project (relative paths, no traversal)
- Targeted edits (str_replace) to any file within the project directory — these are minimal and auditable
- Web searches for public knowledge: docs, error messages, open-source libraries, general programming questions

Guidelines — DENY:
- Path traversal: any path containing ../../, starting with ~/ or an absolute path (e.g. /etc/, C:\\Windows\\)
- Destructive shell commands: rm -rf, DROP DATABASE, format, truncate on production targets
- Sending data to external locations: curl/POST to external URLs, uploading files to external services
- Queries or payloads that embed specific internal names, figures, project codenames, or financial data
  that appear proprietary — these risk leaking confidential information even via a search query

When uncertain whether a search query or transfer contains internal data, use "human".
When in doubt about anything else, deny.{context_section}
"""

_CONTEXT_SECTION = """

Organisation context (use this to identify what counts as internal information):
{context}"""


def _build_system_prompt(context: str | None) -> str:
    section = _CONTEXT_SECTION.format(context=context) if context else ""
    return _SYSTEM_PROMPT_BASE.format(context_section=section)


def llm_approver(
    model: str,
    *,
    context: str | None = None,
) -> Callable[[ToolCallOutput], Awaitable[bool]]:
    """Return an ``on_permission_request`` coroutine that uses an LLM to judge safety.

    Parameters
    ----------
    model:
        Model string passed to :meth:`LLM.converse`, e.g. ``"ollama/granite4:tiny-h"``.
    context:
        Optional description of the organisation and its internal projects/data.
        Helps the LLM distinguish public information from confidential internal details
        when evaluating search queries or data transfers.
        Example: ``"AcmeCorp internal assistant. Internal projects: Nighthawk, Falcon."`
    """
    system_prompt = _build_system_prompt(context)

    async def _approve(call: ToolCallOutput) -> bool:
        display = (
            call.tool_name
            if not call.arguments
            else f"{call.tool_name}({json.dumps(call.arguments, ensure_ascii=False)})"
        )
        user_content = (
            f"Tool: {call.tool_name}\n"
            f"Arguments: {json.dumps(call.arguments, indent=2, ensure_ascii=False)}\n"
            f"Display: {display}"
        )

        try:
            stream = await LLM.converse(
                model=model,
                system_prompt=system_prompt,
                tools=[],
                chat_history=[UserMessage(content=user_content)],
            )

            chunks: list[str] = []
            async for item in stream:
                if isinstance(item, TextDelta):
                    chunks.append(item.text)

            raw = "".join(chunks).strip()
            # Extract JSON — tolerate markdown fences or leading/trailing text
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError(f"No JSON object found in response: {raw!r}")

            parsed = json.loads(raw[start:end])
            verdict: str = parsed.get("decision", "").lower()
            reason: str = parsed.get("reason", "")

            result = verdict == "approved"
            if verdict == "human":
                _log.info(
                    "LLM approver: %s → HUMAN (remapped to DENY) (%s)",
                    display, reason,
                )
                return False

            _log.info(
                "LLM approver: %s → %s (%s)",
                display,
                "APPROVED" if result else "DENIED",
                reason,
            )
            return result

        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "LLM approver error for '%s': %s — defaulting to deny",
                display,
                exc,
            )
            return False

    return _approve
