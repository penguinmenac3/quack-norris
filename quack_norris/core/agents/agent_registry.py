from typing import cast
import os
import shutil
import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from quack_norris.logging import logger
from quack_norris.core.agents.agent import Agent, SimpleAgent


_agents: dict[str, Agent] = {}
_default_model = None


## API
def set_default_agent_llm(default_model: str):
    """Set the default model for agents"""
    global _default_model
    _default_model = default_model


def load_and_watch_agents(agent_directory: str):
    """Start watching the agent directory for changes."""
    _ensure_default_agent_exists(agent_directory)

    if _default_model is None:
        raise RuntimeError("You must first set a default model before you can load and watch a directory.")
    # Load all agents
    for root, _, files in os.walk(agent_directory):
        for file in files:
            if file.endswith(".agent.md"):
                agent_path = os.path.join(root, file)
                _load_agent_from_file(agent_path, agent_directory)
    # Watch for changes
    observer = Observer()
    observer.schedule(_AgentDirectoryWatcher(agent_directory), agent_directory, recursive=True)
    observer.start()


def list_agents() -> dict[str, Agent]:
    """List all agents in the registry."""
    return _agents


def get_agent(name: str) -> Agent:
    """Retrieve an agent by name"""
    return _agents[name]


# Internal
def _ensure_default_agent_exists(agent_directory):
    """Ensure the `auto.agent.md` exists, if not create it using the `_default.auto.agent.md`."""
    here = os.path.dirname(__file__)
    default_agent_src = os.path.join(here, "_default.auto.agent.md")
    default_agent_dst = os.path.join(agent_directory, "auto.agent.md")
    if not os.path.exists(default_agent_dst):
        os.makedirs(agent_directory, exist_ok=True)
        if os.path.exists(default_agent_src):
            shutil.copyfile(default_agent_src, default_agent_dst)
            logger.info(f"Copied default agent to {default_agent_dst}")
        else:
            logger.warning(
                f"WARNING: Default agent file not found at {default_agent_src}"
            )

def _load_agent_from_file(file_path: str, agent_directory: str):
    """Load an agent from a `.agent.md` file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        parts = content.split("---")
        if len(parts) < 3 or parts[0].strip() != "":
            raise ValueError(f"Invalid agent file format. Expected YAML metadata enclosed by '---'. Error in: {file_path}")

        metadata = yaml.safe_load(parts[1])
        system_prompt = "---".join(parts[2:]).strip()

        name = _derive_agent_name(file_path, agent_directory)
        tools = metadata.get("tools", [])
        if isinstance(tools, str):
            tools = [s.strip() for s in tools.split(",")]
        skills = metadata.get("skills", [])
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.split(",")]
        _agents[name] = SimpleAgent(
            name=name,
            description=metadata.get("description", "No description provided."),
            system_prompt=system_prompt,
            tools=tools,
            skills=skills,
            model=metadata.get("model", _default_model),
            system_prompt_last=metadata.get("system_prompt_last", False),
        )
    except Exception as e:
        logger.warning(f"Cannot load agent `{file_path}`. Error occured: {e}")


def _derive_agent_name(file_path: str, agent_directory: str) -> str:
    """Get the agent name based on the file path relative to the agent directory."""
    name = os.path.relpath(file_path, agent_directory)
    return name.replace("/", ".").replace("\\", ".").replace(".agent.md", "")


def _unload_agent_from_file(file_path: str, agent_directory: str):
    """Remove an agent based on its file path."""
    del _agents[_derive_agent_name(file_path, agent_directory)]


class _AgentDirectoryWatcher(FileSystemEventHandler):
    def __init__(self, agent_directory: str):
        self.agent_directory = agent_directory

    def on_created(self, event):
        if isinstance(event.src_path, str) and event.src_path.endswith(".agent.md"):
            _load_agent_from_file(cast(str, event.src_path), self.agent_directory)
            logger.info(f"Agent added: {event.src_path}")

    def on_modified(self, event):
        if isinstance(event.src_path, str) and event.src_path.endswith(".agent.md"):
            _load_agent_from_file(cast(str, event.src_path), self.agent_directory)
            logger.info(f"Agent updated: {event.src_path}")

    def on_deleted(self, event):
        if isinstance(event.src_path, str) and event.src_path.endswith(".agent.md"):
            _unload_agent_from_file(cast(str, event.src_path), self.agent_directory)
            logger.info(f"Agent removed: {event.src_path}")
