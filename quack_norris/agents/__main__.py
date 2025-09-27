import asyncio
import dotenv
import os
import json
import shutil
from quack_norris.core import (
    LLM,
    MCPClient,
    ChatMessage,
    OutputWriter,
)
from quack_norris.agents.agent_definition import AgentDefinition
from quack_norris.agents.agent_runner import AgentRunner
from quack_norris.servers import serve_openai_api


def main(work_dir=None):
    # Setup
    print("Loading environment and llm")
    agents: dict[str, AgentDefinition] = {}
    tools = []
    dotenv.load_dotenv()
    llm, model = LLM.from_env()

    # Define paths
    if work_dir is None:
        home = os.path.expanduser("~")
        work_dir = os.path.join(home, ".config/quack-norris")
    mcp_path = os.path.join(work_dir, "mcps.json")
    agents_path = os.path.join(work_dir, "agents")

    # load tools from MCP servers
    if os.path.exists(mcp_path):
        print("Loading and connecting MCP tools")
        with open(mcp_path, "r") as f:
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
    else:
        print(f"No MCP servers configured. Create a `{work_dir}/mcps.json` to configure them.")

    # Check if default agent exists, if not use the default.auto.agent.md to create it
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
    for root, _, files in os.walk(agents_path):
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

    print("Starting server")
    serve_openai_api(handlers={k: _make_handler(k) for k in agents.keys()})


if __name__ == "__main__":
    main()
