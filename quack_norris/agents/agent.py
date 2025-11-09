from typing import Callable, List
import os
import yaml
import datetime
import uuid

from quack_norris.logging import logger
from quack_norris.core.llm.types import Tool, ToolParameter, ToolCall, ChatMessage, LLM
from quack_norris.core.llm.model_provider import ModelProvider
from quack_norris.core.output_writer import OutputWriter


class Agent(object):
    def __init__(self, name: str, description: str):
        self._name = name
        self._description = description

    def fill_tool_description(self, callback: Callable) -> Tool:
        parameters = self._get_parameters()
        return Tool(
            name="agent." + self._name,
            description=self._description,
            parameters=parameters,
            tool_callable=callback,
        )
    
    def _get_parameters(self):
        return {}

    async def chat(self, messages: list[ChatMessage], output: OutputWriter, available_tools: List[Tool], **kwargs) -> bool:
        raise RuntimeError("Must be implemented by child implementations!")


class SimpleAgent(Agent):
    def __init__(self, name: str, description: str, system_prompt: str, tools: List[str],
                 context_name: str = "context", no_think: bool = True, model: str = "",
                 system_prompt_last: bool = False):
        super().__init__(name, description)
        self._system_prompt = system_prompt
        self._tools = tools
        self._context_name = context_name
        self._no_think = no_think
        self._model = model
        self._system_prompt_last = system_prompt_last

    @staticmethod
    def from_folder(default_model: str, root_dir: str) -> dict[str, Agent]:
        logger.info("Loading agents")
        agents: dict[str, Agent] = {}
        for base_dir, _, files in os.walk(root_dir):
            for fname in files:
                if fname.endswith(".agent.md"):
                    file_path = os.path.join(base_dir, fname)
                    rel_path = os.path.relpath(base_dir, root_dir)
                    agent_name = rel_path.replace("/", ".").replace("\\", ".")
                    agent_name = agent_name + "." + fname.replace(".agent.md", "")
                    while agent_name.startswith("."):
                        agent_name = agent_name[1:]
                    try:
                        agent = SimpleAgent.from_file(
                            default_model, file_path, name=agent_name
                        )
                        agents[agent._name] = agent
                    except Exception as e:
                        logger.warning(f"Failed to load agent `{fname}` for reason {e}")

        logger.info(f"Loaded {len(agents.keys())} agents")
        return agents

    @staticmethod
    def from_file(default_model: str, path: str, name: str="") -> "SimpleAgent":
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
        if model == "":
            model = default_model
        system_prompt_last = bool(yaml_meta.get("system_prompt_last", False))
        if "tools" in yaml_meta:
            tool_filters = yaml_meta.get("tools", "")
            tool_filters = [t.strip() for t in tool_filters.split(",")]
        else:
            tool_filters = []

        context_name = yaml_meta.get("context_name", "context").strip()
        no_think = not bool(yaml_meta.get("think", False))
        return SimpleAgent(
            name=name,
            description=description,
            system_prompt=system_prompt,
            tools=tool_filters,
            context_name=context_name,
            no_think=no_think,
            model=model,
            system_prompt_last=system_prompt_last,
        )

    def _get_parameters(self):
        parameters = {}
        if "{task}" in self._system_prompt:
            parameters["task"] = ToolParameter(
                type="string",
                description="The task to process. If not provided, the agent will extract the task from the chat history."
            )
        if "{" + self._context_name + "}" in self._system_prompt:
            parameters[self._context_name] = ToolParameter(
                type="string",
                description="The context to use for the task. If not provided, the agent will extract the context from the chat history."
            )
        return parameters

    async def chat(self, messages: list[ChatMessage], output: OutputWriter, available_tools: List[Tool], **kwargs) -> bool:
        kwargs["task"] = kwargs["task"] if "task" in kwargs else ""
        kwargs[self._context_name] = kwargs[self._context_name] if self._context_name in kwargs else ""
        if "{today}" in self._system_prompt:
            kwargs["today"] = datetime.datetime.now().strftime("%A, %B %d, %Y")
        if "{now}" in self._system_prompt:
            kwargs["now"] = datetime.datetime.now().strftime("%A, %B %d, %Y, %H:%M:%S")
        system_prompt = self._system_prompt.format(**kwargs)

        # Collect tools
        current_tools = [
            tool
            for tool in available_tools
            if _tool_matches(tool.name, self._tools) and tool.name != f"agent.{self._name}"
        ]
        # logger.info(f"Tools (all) {[tool.name for tool in tools]}")
        # logger.info(f"Tools (current) {[tool.name for tool in current_tools]}")

        # Add limitations to agent what it does and encourage handover
        system_prompt += "\n\n"
        if len(current_tools) > 0:
            system_prompt += "Final note, if you think a question / task is not in your competence call the agent better suited for it. If no agent matches the `agent.auto` is the front desk taking care of it.\n"
        system_prompt += "If you cannot answer a question, because it does not fit to your job and you cannot give it to another agent. Let the user politely know."

        # Send request to LLM
        llm = ModelProvider.get_llm(self._model)
        response = llm(
            messages=messages[-10:], # only pass last 10 messages to AI
            tools=current_tools,
            system_prompt=system_prompt,
            no_think=self._no_think,
            stream=True,
        )

        # Stream the response
        is_thinking = False
        for chunk in response.stream:
            if chunk == "<think>":
                is_thinking = True
            if chunk == "</think>":
                is_thinking = False
            if not is_thinking:
                await output.default(chunk, end="")
            else:
                await output.thought(chunk, end="")

        # Add the response to the history
        messages.append(ChatMessage(
            role="assistant",
            content=response.text,
            tool_calls=response.tool_calls
        ))

        # Process tool calls and add their results to the history
        for tool_call in response.tool_calls:
            if isinstance(tool_call, ToolCall):
                await output.thought(
                    f"Calling Tool: `{tool_call.tool.name}` with params `{tool_call.params}`"
                )
                result = tool_call.tool.tool_callable(**tool_call.params)
                if hasattr(result, "__await__"):  # Await async tool calls
                    result = await result
                result = str(result)
                messages.append(ChatMessage(role="tool", content=result, tool_call_id=tool_call.id))
                await output.thought(f"Result:\n\n```\n{result}\n```\n")
            else:
                await output.thought(f"Failed parsing toolcall: `{tool_call}`")
                result = f"Failed parsing toolcall with error: `{tool_call}`."
                messages.append(ChatMessage(role="tool", content=result, tool_call_id=str(uuid.uuid4())))
                await output.thought(f"Result:\n\n```\n{tool_call}\n```\n")

        await output.default("")
                    

        # Exit if we did not call a tool, so we can return the flow to the user
        if len(response.tool_calls) == 0:
            logger.info("Exiting runner: No tool call!")
            return True
        return False


def _tool_matches(tool_name: str, tool_filters: list[str]) -> bool:
    for filter_str in tool_filters:
        if tool_name == filter_str:
            return True
        if filter_str.endswith("*") and tool_name.startswith(filter_str[:-1]):
            return True
    return False
