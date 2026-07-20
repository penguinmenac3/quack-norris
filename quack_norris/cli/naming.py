"""Session name auto-generation — one-shot LLM call after the first turn.

The single entry point is :func:`generate_session_name`. It asks the model
for a short, descriptive title based on the first user message and the
assistant's first reply, so sessions are recognisable in the session menu
and via ``--resume`` without needing to open them.
"""

from __future__ import annotations

from quack_norris.core.llm import LLM, TextDelta, UserMessage

_NAME_SYSTEM = """\
You generate short, descriptive titles for a coding assistant's session \
list. Given the user's first message and the assistant's first reply, \
produce a concise title (3-6 words) that captures what the conversation is \
about. No punctuation at the end, no quotes, no markdown, no greetings or \
meta-commentary. Reply with the title only.
"""

_MAX_INPUT_CHARS = 2000
_MAX_NAME_LENGTH = 60


async def generate_session_name(user_text: str, assistant_text: str, model: str) -> str | None:
    """Return a short title summarising the first turn, or ``None`` on failure."""
    prompt = (
        f"User message: {user_text[:_MAX_INPUT_CHARS]}\n\n"
        f"Assistant reply: {assistant_text[:_MAX_INPUT_CHARS]}\n\n"
        "Give this conversation a short title."
    )

    chunks: list[str] = []
    try:
        stream = await LLM.converse(
            model=model,
            system_prompt=_NAME_SYSTEM,
            tools=[],
            chat_history=[UserMessage(content=prompt)],
        )
        async for item in stream:
            if isinstance(item, TextDelta):
                chunks.append(item.text)
    except Exception:  # noqa: BLE001
        return None

    name = " ".join("".join(chunks).strip().strip("\"'").split())
    if not name:
        return None
    if len(name) > _MAX_NAME_LENGTH:
        name = name[:_MAX_NAME_LENGTH].rstrip()
    return name
