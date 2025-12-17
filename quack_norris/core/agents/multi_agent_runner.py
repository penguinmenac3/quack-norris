import os
import asyncio

from quack_norris.config import Config
from quack_norris.logging import logger
from quack_norris.api.chat_handler import ChatHandler, ChatHandlerRegistry, ChatHandlerProvider
from quack_norris.core.agents.skill_registry import load_and_watch_skills
from quack_norris.core.agents.agent_registry import set_default_agent_llm, load_and_watch_agents, list_agents, get_agent
from quack_norris.core.llm.types import ChatMessage, Tool
from quack_norris.core.output_writer import OutputWriter
from quack_norris.core.tools.mcp import initialize_mcp_tools


class MultiAgentRunner(ChatHandlerProvider):
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
    def setup_from_config(config: Config) -> None:
        # load tools from MCP servers
        tools: list[Tool] = []
        if "mcps" in config:
            tools = asyncio.run(initialize_mcp_tools(config["mcps"]))
        else:
            logger.warning(
                "No MCP servers configured. Add a `mcps` section to your config.json to configure them."
            )

        # Load agents and skills
        set_default_agent_llm(config.get("default_model", "gemma3:12b"))
        for path in [config.code_home_path, config.user_home_path, config.local_path]:
            full_path = os.path.join(path, "agents")
            if os.path.exists(full_path):
                load_and_watch_agents(full_path)
                load_and_watch_skills(full_path)
        runner = MultiAgentRunner(default_agent="auto", tools=tools)
        ChatHandlerRegistry.register_handler_provider(runner)

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

    def get_handler(self, name: str) -> ChatHandler:
        if name not in self.list_handlers():
            raise RuntimeError(f"Model/Agent '{name}' not found in multi-agent runner provider.")
        name = name.replace("agent.", "")
        if name == self._default_agent:
            name = ""

        def _handle_chat(history: list[ChatMessage], workspace: str, output: OutputWriter):
            return self.chat(
                messages=history, workspace=workspace, output=output, agent_name=name
            )

        return _handle_chat
    
    def list_handlers(self) -> list[str]:
        return [f"agent.{k}" for k in list_agents().keys()]

    async def chat(
        self,
        messages: list[ChatMessage],
        workspace: str,
        output: OutputWriter,
        agent_name: str = "",
    ) -> None:
        # TODO integrate filesystem tool and handle the workspace correctly
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
