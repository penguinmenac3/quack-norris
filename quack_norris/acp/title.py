from __future__ import annotations

import asyncio
import re

from quack_norris.core import LLM
from quack_norris.core.llm import TextDelta, UserMessage

_TITLE_PROMPT = """Create a concise 3-7 word title for this coding-agent session.
Return only the title, without quotes, markdown, or punctuation.

User request:
{user_text}

Agent result:
{assistant_text}
"""


async def generate_session_title(
    user_text: str,
    assistant_text: str,
    model: str,
    *,
    timeout: float = 5.0,
) -> str:
    async def _generate() -> str:
        stream = await LLM.converse(
            model=model,
            system_prompt="You create short session titles.",
            tools=[],
            chat_history=[
                UserMessage(
                    content=_TITLE_PROMPT.format(
                        user_text=user_text[:2000],
                        assistant_text=assistant_text[:2000],
                    )
                )
            ],
        )
        chunks: list[str] = []
        async for item in stream:
            if isinstance(item, TextDelta):
                chunks.append(item.text)
        return _clean_title("".join(chunks))

    try:
        title = await asyncio.wait_for(_generate(), timeout=timeout)
    except Exception:  # noqa: BLE001
        title = ""
    return title or fallback_title(user_text)


def fallback_title(user_text: str) -> str:
    normalized = " ".join(user_text.split())
    if len(normalized) <= 60:
        return normalized
    prefix = normalized[:57].rsplit(" ", 1)[0]
    return prefix.rstrip() + "..."


def _clean_title(value: str) -> str:
    line = next((line.strip() for line in value.splitlines() if line.strip()), "")
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = line.strip("`*_\"' ")
    line = re.sub(r"[.!?:;,]+$", "", line).strip()
    words = line.split()
    if len(words) > 7:
        line = " ".join(words[:7])
    return line[:80].strip()
