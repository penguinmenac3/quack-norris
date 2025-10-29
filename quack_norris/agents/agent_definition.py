from typing import Callable, List
import yaml
from pydantic import BaseModel

from quack_norris.core.llm import Tool


class AgentDefinition(BaseModel):
    name: str
    description: str
    system_prompt: str
    tool_filters: List[str]
    context_name: str = "context"
    no_think: bool = True
    model: str = ""
    system_prompt_last: bool = False

    @staticmethod
    def from_file(path: str, name: str="") -> "AgentDefinition":
        with open(path, "r", encoding="utf-8") as f:
            prompt = f.read()
        parts = prompt.split("---")
        if len(parts) < 3 or parts[0].strip() != "":
            raise RuntimeError(
                "Prompt must start with '---' followed by YAML metadata and another '---'."
            )
        system_prompt = "---".join(parts[2:]).strip()
        meta = parts[1]
        yaml_meta = yaml.safe_load(meta)
        if name == "":
            name = yaml_meta.get("name", "Agent").strip()
        description = yaml_meta.get(
            "description", "An agent that can process user queries and provide answers."
        ).strip()
        model = yaml_meta.get("model", "").strip()
        system_prompt_last = bool(yaml_meta.get("system_prompt_last", False))
        if "tools" in yaml_meta:
            tool_filters = yaml_meta.get("tools", "")
            tool_filters = [t.strip() for t in tool_filters.split(",")]
        else:
            tool_filters = []

        context_name = yaml_meta.get("context_name", "context").strip()
        no_think = not bool(yaml_meta.get("think", False))
        return AgentDefinition(
            name=name,
            description=description,
            system_prompt=system_prompt,
            tool_filters=tool_filters,
            context_name=context_name,
            no_think=no_think,
            model=model,
            system_prompt_last=system_prompt_last,
        )

    def _as_tool(self, callback: Callable) -> Tool:
        if "{task}" in self.system_prompt:
            task = "  - task: The task to process. If not provided, the agent will extract the task from the chat history.\n"
        else:
            task = ""
        if "{" + self.context_name + "}" in self.system_prompt:
            ctx = f"  - {self.context_name}: The context to use for the task. If not provided, the agent will extract the context from the chat history.\n"
        else:
            ctx = ""
        return Tool(
            name="agent." + self.name,
            description=self.description,
            arguments=(task + ctx).strip("\n"),
            tool_callable=callback,
        )
