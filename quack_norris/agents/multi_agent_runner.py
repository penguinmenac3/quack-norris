from typing import Any
import os
import asyncio

from quack_norris.logging import logger
from quack_norris.core import ChatMessage, Tool, OutputWriter
from quack_norris.servers import ChatHandler
from quack_norris.tools.mcp import initialize_mcp_tools

from quack_norris.agents.skill_registry import load_and_watch_skills
from quack_norris.agents.agent_registry import set_default_agent_llm, load_and_watch_agents, list_agents, get_agent


class MultiAgentRunner:
    def __init__(
        self,
        default_agent: str,
        tools: list[Tool],
        max_steps: int = 15,
    ):
        self._default_agent = default_agent
        self._tools = tools
        self._max_steps = max_steps

    @staticmethod
    def from_config(
        config: dict[str, Any], config_path: str
    ) -> "MultiAgentRunner":
        # load tools from MCP servers
        tools: list[Tool] = []
        if "mcps" in config:
            tools = asyncio.run(initialize_mcp_tools(config["mcps"]))
        else:
            logger.warning(
                f"No MCP servers configured. Add a `mcps` section to `{config_path}` to configure them."
            )

        # Load agents and skills
        agents_path = os.path.join(os.path.dirname(config_path), "agents")
        set_default_agent_llm(config.get("default_model", "gemma3:12b"))
        load_and_watch_agents(agents_path)
        load_and_watch_skills(agents_path)
        return MultiAgentRunner(default_agent="auto", tools=tools)

    def add_tools(self, tools: list[Tool]):
        for tool in tools:
            if tool not in self._tools:
                self._tools.append(tool)

    def _determine_agent(self, history: list[ChatMessage]) -> str:
        agent = self._default_agent
        for message in history:
            text = message.text()
            if "Successfully switched to agent: `" in text:
                for line in text.split("\n"):
                    if "Successfully switched to agent: `" in line:
                        agent = line.replace(
                            "Successfully switched to agent: `", ""
                        ).replace("`", "")
        if agent not in list_agents().keys():
            agent = self._default_agent
        logger.info(f"Active agent: `{agent}`")
        return agent

    def make_chat_handlers(self) -> dict[str, ChatHandler]:
        def _make_handler(agent):
            if agent == self._default_agent:
                agent = ""

            def _handle_chat(history: list[ChatMessage], output: OutputWriter):
                return self.chat(agent_name=agent, messages=history, output=output)

            return _handle_chat
    
        return {f"agent.{k}": _make_handler(k) for k in list_agents().keys()}

    async def chat(
        self, messages: list[ChatMessage], output: OutputWriter, agent_name: str = ""
    ) -> None:
        tools = list(self._tools)  # copy so we can locally modify
        kwargs = {}

        # Allow switching of agent during conversation, if no agent is provided
        if agent_name == "":

            def _switch_tool(agent: str):
                async def _callback(**args: dict):
                    nonlocal agent_name
                    nonlocal kwargs
                    if agent in list_agents().keys():
                        agent_name = agent
                        kwargs = args
                        logger.info(f"Successfully switched to agent: `{agent}`")
                        return f"Successfully switched to agent: `{agent}`"
                    else:
                        logger.info(
                            f"Failed to switch agent, unknown agent name: `{agent}`"
                        )
                        return f"Failed to switch agent, unknown agent name: `{agent}`"

                return _callback

            agent_name = self._determine_agent(messages)
            tools += [
                agent.fill_tool_description(_switch_tool(key))
                for key, agent in list_agents().items()
            ]

        for step in range(max(self._max_steps, 1)):
            current_tools: list[Tool] = tools if step < self._max_steps - 1 else []
            is_done: bool = await get_agent(agent_name).chat(
                messages, output, current_tools, **kwargs
            )
            if is_done:
                return
