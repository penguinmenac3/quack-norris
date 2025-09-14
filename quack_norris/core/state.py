
from typing import List, TypedDict

from quack_norris.core.output_writer import OutputWriter
from quack_norris.core.llm import ChatMessage


class SharedAgentState(TypedDict):
    # Read only (across all steps of the conversation)
    chat_messages: List[ChatMessage]  # Messages from the chat with the user
    writer: OutputWriter  # Write to the user chat


def build_agent_state(chat_messages: List[ChatMessage], writer: OutputWriter):
    return {
        "chat_messages": chat_messages,
        "writer": writer,
    }
