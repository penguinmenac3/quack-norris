from typing import cast, Callable
import os
import shutil
import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from quack_norris.logging import logger
from quack_norris.config import Config
from quack_norris.core.agents.agent import Agent, remove_agent, update_agent
from quack_norris.core.agents.skill import Skill, remove_skill, update_skill


_default_model: str = ""


def load_and_watch_agents_and_skills(config: Config):
    global _default_model
    _default_model = config.get("default_model", "gemma3:12b")

    # Load agents and skills
    for path in [config.code_home_path, config.user_home_path, config.local_path]:
        full_path = os.path.join(path, "agents")
        if os.path.exists(full_path):
            _load_and_watch(full_path)


# Internals
def _load_and_watch(directory: str):
    """Start watching the agent directory for changes."""
    _ensure_default_agent_exists(directory)

    # Load all agents
    for root, _, files in os.walk(directory):
        for fname in files:
            if fname.endswith(".agent.md") or fname.endswith(".skill.md"):
                fpath = os.path.join(root, fname)
                _load_from_file(fpath, directory)
    # Watch for changes
    observer = Observer()
    observer.schedule(
        _DirectoryWatcher(_load_from_file, _unload_from_file, directory), directory, recursive=True
    )
    observer.start()


def _ensure_default_agent_exists(directory):
    """Ensure the `auto.agent.md` exists, if not create it using the `_default.auto.agent.md`."""
    here = os.path.dirname(__file__)
    default_agent_src = os.path.join(here, "_default.auto.agent.md")
    default_agent_dst = os.path.join(directory, "auto.agent.md")
    if not os.path.exists(default_agent_dst):
        os.makedirs(directory, exist_ok=True)
        if os.path.exists(default_agent_src):
            shutil.copyfile(default_agent_src, default_agent_dst)
            logger.info(f"Copied default agent to {default_agent_dst}")
        else:
            logger.warning(f"WARNING: Default agent file not found at {default_agent_src}")


def _load_from_file(file_path: str, agent_directory: str):
    """Load an agent from a `.agent.md` file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        parts = content.split("---")
        if len(parts) < 3 or parts[0].strip() != "":
            raise ValueError(
                f"Invalid agent file format. Expected YAML metadata enclosed by '---'. Error in: {file_path}"
            )

        metadata = yaml.safe_load(parts[1])
        prompt = "---".join(parts[2:]).strip()

        name = _derive_name(file_path, agent_directory)
        tools = metadata.get("tools", [])
        if isinstance(tools, str):
            tools = [s.strip() for s in tools.split(",")]
        if file_path.endswith(".agent.md"):
            skills = metadata.get("skills", [])
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.split(",")]
            update_agent(name, Agent(
                system_prompt=prompt,
                model=metadata.get("model", _default_model),
                description=metadata.get("description", "No description provided."),
                max_steps=metadata.get("max_steps", 10),
                tools=tools,
                skills=skills,
            ))
        else:
            update_skill(name, Skill(
                description=metadata.get("description", ""),
                tools=tools,
                prompt=prompt,
            ))
    except Exception as e:
        logger.warning(f"Cannot load agent `{file_path}`. Error occured: {e}")


def _derive_name(file_path: str, agent_directory: str) -> str:
    """Get the agent name based on the file path relative to the agent directory."""
    name = os.path.relpath(file_path, agent_directory)
    return name.replace("/", ".").replace("\\", ".").replace(".agent.md", "")


def _unload_from_file(file_path: str, agent_directory: str):
    """Remove an agent based on its file path."""
    if file_path.endswith(".agent.md"):
        remove_agent(_derive_name(file_path, agent_directory))
    else:
        remove_skill(_derive_name(file_path, agent_directory))


class _DirectoryWatcher(FileSystemEventHandler):
    def __init__(self, load_from_file: Callable, unload_from_file: Callable, directory: str):
        self.load_from_file = load_from_file
        self.unload_from_file = unload_from_file
        self.directory = directory

    def on_created(self, event):
        if isinstance(event.src_path, str) and (event.src_path.endswith(".agent.md") or event.src_path.endswith(".skill.md")):
            self.load_from_file(cast(str, event.src_path), self.directory)
            logger.info(f"Agent added: {event.src_path}")

    def on_modified(self, event):
        if isinstance(event.src_path, str) and (event.src_path.endswith(".agent.md") or event.src_path.endswith(".skill.md")):
            self.load_from_file(cast(str, event.src_path), self.directory)
            logger.info(f"Agent updated: {event.src_path}")

    def on_deleted(self, event):
        if isinstance(event.src_path, str) and (event.src_path.endswith(".agent.md") or event.src_path.endswith(".skill.md")):
            self.unload_from_file(cast(str, event.src_path), self.directory)
            logger.info(f"Agent removed: {event.src_path}")
