import os
import yaml
from typing import Dict, Optional, NamedTuple
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from quack_norris.logging import logger


class Skill(NamedTuple):
    name: str
    description: str
    tools: list[str]
    prompt: str


_skills: Dict[str, Skill] = {}


## API
def load_and_watch_skills(skill_directory: str):
    """Start watching the skill directory for changes."""
    # Load the skills
    for root, _, files in os.walk(skill_directory):
        for file in files:
            if file.endswith(".skill.md"):
                skill_path = os.path.join(root, file)
                _load_skill_from_file(skill_path, skill_directory)
    # Watch for changes
    _observer = Observer()
    _observer.schedule(_SkillFileChangeHandler(skill_directory), skill_directory, recursive=True)
    _observer.start()


def list_skills() -> dict[str, Skill]:
    """List all skills in the registry."""
    return _skills


def get_skill(name: str) -> Optional[Skill]:
    """Retrieve a skill by name."""
    return _skills.get(name)


## Internals
def _load_skill_from_file(path: str, skill_directory: str):
    """Load a single skill from a .skill.md file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        parts = content.split("---")
        if len(parts) < 3 or parts[0].strip() != "":
            raise ValueError(f"Invalid skill file format. Expected YAML metadata enclosed by '---'. Error in: {path}")

        metadata = yaml.safe_load(parts[1])
        prompt = "---".join(parts[2:]).strip()

        skill_name = _derive_skill_name(path, skill_directory)
        tools = metadata.get("tools", [])
        if isinstance(tools, str):
            tools = [s.strip() for s in tools.split(",")]
        _skills[skill_name] = Skill(
            name=skill_name,
            description=metadata.get("description", ""),
            tools=tools,
            prompt=prompt,
        )
    except Exception as e:
        logger.warning(f"Cannot load skill `{path}`. Error occured: {e}")


def _derive_skill_name(file_path: str, skill_directory: str) -> str:
    """Get the agent name based on the file path relative to the agent directory."""
    name = os.path.relpath(file_path, skill_directory)
    return name.replace("/", ".").replace("\\", ".").replace(".skill.md", "")


def _unload_skill_from_file(file_path: str, skill_directory: str):
    """Remove a skill based on its file path."""
    del _skills[_derive_skill_name(file_path, skill_directory)]


class _SkillFileChangeHandler(FileSystemEventHandler):
    def __init__(self, skill_directory: str):
        self._skill_directory = skill_directory

    def on_modified(self, event):
        if isinstance(event.src_path, str) and event.src_path.endswith(".skill.md"):
            _load_skill_from_file(event.src_path, self._skill_directory)
            logger.info(f"Skill added: {event.src_path}")

    def on_created(self, event):
        if isinstance(event.src_path, str) and event.src_path.endswith(".skill.md"):
            _load_skill_from_file(event.src_path, self._skill_directory)
            logger.info(f"Skill updated: {event.src_path}")

    def on_deleted(self, event):
        if isinstance(event.src_path, str) and event.src_path.endswith(".skill.md"):
            _unload_skill_from_file(event.src_path, self._skill_directory)
            logger.info(f"Skill removed: {event.src_path}")
