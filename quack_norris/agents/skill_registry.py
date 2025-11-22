import os
import yaml
from typing import Dict, Optional, NamedTuple
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class Skill(NamedTuple):
    name: str
    description: str
    tools: list[str]
    prompt: str


class SkillRegistry:
    def __init__(self, skill_directory: str):
        self._skill_directory = skill_directory
        self._skills: Dict[str, Skill] = {}
        self._observer = Observer()
        self._start_watching()
        self._load_skills()

    def _start_watching(self):
        """Start watching the skill directory for changes."""
        event_handler = _SkillFileChangeHandler(self)
        self._observer.schedule(event_handler, self._skill_directory, recursive=True)
        self._observer.start()

    def _load_skills(self):
        """Load all skills from the skill directory."""
        for root, _, files in os.walk(self._skill_directory):
            for file in files:
                if file.endswith(".skill.md"):
                    skill_path = os.path.join(root, file)
                    self._load_skill_from_file(skill_path)

    def _load_skill_from_file(self, path: str):
        """Load a single skill from a .skill.md file."""
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        parts = content.split("---")
        if len(parts) < 3:
            raise ValueError(f"Invalid skill file format: {path}")
        metadata = yaml.safe_load(parts[1])
        prompt = "---".join(parts[2:]).strip()

        # Determine skill name with folder prefix
        rel_path = os.path.relpath(path, self._skill_directory)
        folder_prefix = os.path.dirname(rel_path).replace(os.sep, ".")
        base_name = os.path.basename(path).replace(".skill.md", "")
        skill_name = metadata.get("name", base_name)
        if folder_prefix:
            skill_name = f"{folder_prefix}.{skill_name}"

        skill = Skill(
            name=skill_name,
            description=metadata.get("description", ""),
            tools=metadata.get("tools", []),
            prompt=prompt,
        )
        self._skills[skill.name] = skill

    def get_skill(self, name: str) -> Optional[Skill]:
        """Retrieve a skill by name."""
        return self._skills.get(name)

    def stop_watching(self):
        """Stop the file observer."""
        self._observer.stop()
        self._observer.join()


class _SkillFileChangeHandler(FileSystemEventHandler):
    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def on_modified(self, event):
        if not isinstance(event.src_path, str):
            raise NotImplementedError("Only str paths supported!")
        if event.src_path.endswith(".skill.md"):
            self.registry._load_skill_from_file(event.src_path)

    def on_created(self, event):
        if not isinstance(event.src_path, str):
            raise NotImplementedError("Only str paths supported!")
        if event.src_path.endswith(".skill.md"):
            self.registry._load_skill_from_file(event.src_path)

    def on_deleted(self, event):
        if not isinstance(event.src_path, str):
            raise NotImplementedError("Only str paths supported!")
        if event.src_path.endswith(".skill.md"):
            rel_path = os.path.relpath(event.src_path, self.registry._skill_directory)
            folder_prefix = os.path.dirname(rel_path).replace(os.sep, ".")
            base_name = os.path.basename(event.src_path).replace(".skill.md", "")
            skill_name = f"{folder_prefix}.{base_name}" if folder_prefix else base_name
            self.registry._skills.pop(skill_name, None)
