import asyncio
import dotenv
import os
import json
from quack_norris.core import Agent, LLM, MCPClient
from quack_norris.servers import serve_openai_api


def main(work_dir=os.path.dirname(__file__)):
    # Setup
    agents: dict[str, Agent] = {}
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
            if fname.endswith(".md"):
                if fname.endswith("README.md"):
                    continue
                file_path = os.path.join(root, fname)
                with open(file_path, "r", encoding="utf-8") as f:
                    md = f.read()
                try:
                    agent = Agent(llm, model, md, no_think=True)
                    agents[agent.name] = agent
                except Exception as e:
                    print(f"WARNING: Failed to load agent `{fname}` for reason {e}")

    # Set the tools and agents as tools for other agents
    for name, agent in agents.items():
        agents_as_tools = [a.as_tool() for a in agents.values() if a is not agent]
        agent.set_tools(tools + agents_as_tools)

    # Serve agents via chat api
    serve_openai_api({k: v for k, v in agents.items()})


if __name__ == "__main__":
    main()
