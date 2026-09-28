"""Minimal agent smoke test; requires copilot/gpt-5.6-luna in llms.yaml."""

import asyncio

from quack_norris.core.agent import AgentOutput, TextOutput, ToolCallOutput, agent
from quack_norris.core.llm import LLM, UserMessage, tool

_tool_calls: list[str] = []


@tool
def hello_world(name: str) -> str:
    """Return a recognizable greeting to verify the model called this tool."""
    _tool_calls.append(name)
    return f"TOOL WAS CALLED: Hello, {name}!"


async def main() -> None:
    LLM.setup()

    async def on_output(output: AgentOutput) -> None:
        if isinstance(output, TextOutput):
            print(output.text, end="", flush=True)

    async def on_permission_request(_call: ToolCallOutput) -> bool:
        return False

    await agent(
        model="copilot/gpt-5.6-luna",
        system_prompt="You are a concise assistant.",
        tools=[hello_world],
        chat_history=[
            UserMessage(content="Use hello_world with name='world', then report its result.")
        ],
        on_permission_request=on_permission_request,
        on_output=on_output,
    )
    print()
    print(f"hello_world tool called: {'yes' if _tool_calls else 'no'}")


if __name__ == "__main__":
    asyncio.run(main())
