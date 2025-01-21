from typing import NamedTuple


class Message(NamedTuple):
    role: str
    content: str


class EmbedResponse(NamedTuple):
    prompt_tokens: int
    total_tokens: int
    embeds: list[str]


class TextResponse(NamedTuple):
    prompt_tokens: int
    total_tokens: int
    finish_reason: str
    result: str
