from typing import Any
import asyncio
import os
import shutil

from quack_norris.core import (
    LLM,
    MCPClient,
    ChatMessage,
    OutputWriter,
)
from quack_norris.agents.agent_definition import AgentDefinition
from quack_norris.agents.agent_runner import AgentRunner
from quack_norris.servers import ChatHandler


def make_agent_handlers(config: dict[str, Any], llm: LLM, work_dir: str, config_path: str) -> dict[str, ChatHandler]:
    # load tools from MCP servers
    tools = []
    if "mcps" in config:
        print("Connecting to MCPs")
        mcps = config["mcps"]
        async def _gather_tools():
            tasks = []
            for name, mcp_config in mcps.items():
                name = (
                    name.replace("-", "_")
                    .replace("/", "_")
                    .replace(".", "_")
                    .replace("(", "_")
                    .replace(")", "_")
                )
                client = MCPClient(**mcp_config)
                tasks.append(client.list_tools(prefix=f"{name}."))
            for result in await asyncio.gather(*tasks, return_exceptions=True):
                if isinstance(result, Exception):
                    print(f"WARNING: Failed to gather tools from MCP for reason: {result}")
                else:
                    tools.extend(result)  #type: ignore

        asyncio.run(_gather_tools())
        print("MCP Tools Discovered")
        for tool in tools:
            print(f"* {tool.name}: {tool.description}")
        print(f"Connected {len(tools)} tools")
    else:
        print(f"No MCP servers configured. Add a `mcps` section to `{config_path}` to configure them.")

    # Check if default agent exists, if not use the default.auto.agent.md to create it
    agents_path = os.path.join(work_dir, "agents")
    here = os.path.dirname(__file__)
    default_agent_src = os.path.join(here, "default.auto.agent.md")
    default_agent_dst = os.path.join(agents_path, "auto.agent.md")
    if not os.path.exists(default_agent_dst):
        os.makedirs(agents_path, exist_ok=True)
        if os.path.exists(default_agent_src):
            shutil.copyfile(default_agent_src, default_agent_dst)
            print(f"Copied default agent to {default_agent_dst}")
        else:
            print(f"WARNING: Default agent file not found at {default_agent_src}")

    # Load agents from md files in all subdirectories
    print("Loading agent definitions")
    agents: dict[str, AgentDefinition] = {}
    for root, _, files in os.walk(agents_path):
        for fname in files:
            if fname.endswith(".agent.md"):
                file_path = os.path.join(root, fname)
                rootname = os.path.relpath(root, agents_path)
                rootname = rootname.replace("/", ".").replace("\\", ".")
                agent_name = rootname + "." + fname.replace(".agent.md", "")
                while agent_name.startswith("."):
                    agent_name = agent_name[1:]
                try:
                    agent = AgentDefinition.from_file(file_path, name=agent_name)
                    agents[agent.name] = agent
                except Exception as e:
                    print(f"WARNING: Failed to load agent `{fname}` for reason {e}")

    print(f"Loaded {len(agents.keys())} agents")
    runner = AgentRunner(
        llm=llm, default_agent="auto", agents=agents, tools=tools
    )

    # Serve agents via chat api
    def _make_handler(agent):
        if agent == runner._default_agent:
            agent = ""

        def _handle_chat(history: list[ChatMessage], output: OutputWriter):
            return runner.process_request(agent_name=agent, history=history, output=output)

        return _handle_chat
    
    return {f"agent.{k}": _make_handler(k) for k in agents.keys()}
