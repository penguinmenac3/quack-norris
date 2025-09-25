import asyncio
import dotenv
import os
import json
from quack_norris.core import (
    LLM,
    MCPClient,
    ChatMessage,
    OutputWriter,
)
from quack_norris.agents.agent_definition import AgentDefinition
from quack_norris.agents.agent_runner import AgentRunner
from quack_norris.servers import serve_openai_api


def main(work_dir=os.path.dirname(__file__)):
    # Setup
    agents: dict[str, AgentDefinition] = {}
    tools = []
    dotenv.load_dotenv()
    llm, model = LLM.from_env()

    # load tools from MCP servers
    with open(os.path.join(work_dir, "mcps.json"), "r") as f:
        mcps = json.load(f)["servers"]
    for name, config in mcps.items():
        name = (
            name.replace("-", "_")
            .replace("/", "_")
            .replace(".", "_")
            .replace("(", "_")
            .replace(")", "_")
        )
        try:
            client = MCPClient(**config)
            tools += asyncio.run(client.list_tools(prefix=f"{name}."))
        except:
            print(f"WARNING: Failed to set up MCP `{name}`")

    print("MCP Tools Discovered")
    for tool in tools:
        print(f"* {tool.name}: {tool.description}")

    # Load agents from md files in all subdirectories
    for root, _, files in os.walk(work_dir):
        for fname in files:
            if fname.endswith(".agent.md"):
                file_path = os.path.join(root, fname)
                try:
                    agent = AgentDefinition.from_file(file_path)
                    agents[agent.name] = agent
                except Exception as e:
                    print(f"WARNING: Failed to load agent `{fname}` for reason {e}")

    runner = AgentRunner(
        llm=llm, model=model, default_agent="auto", agents=agents, tools=tools
    )

    # Serve agents via chat api
    def _make_handler(agent):
        if agent == runner._default_agent:
            agent = ""

        def _handle_chat(history: list[ChatMessage], output: OutputWriter):
            return runner.process_request(agent_name=agent, history=history, output=output)

        return _handle_chat

    serve_openai_api(handlers={k: _make_handler(k) for k in agents.keys()})


if __name__ == "__main__":
    main()
