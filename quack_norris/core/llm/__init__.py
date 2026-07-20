"""
quack_norris.core.llm
~~~~~~~~~~~~~~~~~~~~~

Public surface::

    LLM.setup()              # merge ~/.quack-norris/config.yaml with cwd's config.yaml/llms.yaml
    LLM.setup(path)          # merge ~/.quack-norris/config.yaml with a specific local file
    LLM.converse(model, ...) # stream a turn

Model strings use the ``group/model-name`` convention — identical to
quack-norris-2.0 — e.g. ``"ollama/qwen3:14b"`` or ``"openai/gpt-4o"``.

Config format (``defaults:``, ``compaction:``, ``llms:`` keys in any YAML file;
see :mod:`quack_norris.core.llm.config` for the full merge semantics)::

    defaults:
      model: ollama/qwen3:14b

    llms:
      - group: ollama
        provider: OpenAI
        api_endpoint: http://localhost:11434/v1
      - group: openai
        provider: OpenAI
        api_endpoint: https://api.openai.com/v1
        api_key: ${OPENAI_API_KEY}
        models: [gpt-4o, gpt-4o-mini]
      - group: nexus
        provider: AWSBedrock
        api_endpoint: https://bedrock.corp.example.com
        api_key: ${AWS_BEARER_TOKEN_BEDROCK}
        region: us-east-1
      - group: azure
        provider: AzureOpenAI
        api_endpoint: https://my-resource.openai.azure.com
        api_key: ${AZURE_OPENAI_KEY}
        api_version: "2024-02-01"
"""

from quack_norris.core.llm.config import CompactionConfig
from quack_norris.core.llm.llm import LLM
from quack_norris.core.llm.provider import (
    AssistantMessage,
    ChatMessage,
    LLMOutput,
    TextDelta,
    ThinkingDelta,
    ToolResultMessage,
    UsageInfo,
    UserMessage,
)
from quack_norris.core.llm.tool import ApprovalState, Param, Tool, ToolCallRequest, ToolResult, tool

__all__ = [
    # Facade
    "LLM",
    "CompactionConfig",
    # Tool primitives
    "tool",
    "Param",
    "Tool",
    "ToolResult",
    "ApprovalState",
    # Stream output types
    "LLMOutput",
    "TextDelta",
    "ThinkingDelta",
    "ToolCallRequest",
    "UsageInfo",
    # Chat history types
    "ChatMessage",
    "UserMessage",
    "AssistantMessage",
    "ToolResultMessage",
]
