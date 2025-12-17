from typing import Callable, List
import datetime
import uuid

from quack_norris.logging import logger
from quack_norris.core.agents.skill_registry import Skill, get_skill, list_skills
from quack_norris.core.llm.types import Tool, ToolParameter, ToolCall, ChatMessage
from quack_norris.core.llm.model_provider import ModelProvider
from quack_norris.core.output_writer import OutputWriter


class Agent:
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

    def _get_parameters(self) -> dict[str, ToolParameter]:
        return {}

    async def chat(self, messages: list[ChatMessage], output: OutputWriter, available_tools: list[Tool], **kwargs) -> bool:
        raise RuntimeError("Must be implemented by child implementations!")


class SimpleAgent(Agent):
    def __init__(self, name: str, description: str, system_prompt: str,
                 tools: List[str], skills: List[str],
                 model: str, system_prompt_last: bool):
        super().__init__(name, description)
        self._system_prompt = system_prompt
        self._tools = tools
        self._model = model
        self._skills = skills or []
        self._system_prompt_last = system_prompt_last

    def _determine_skill(self, history: list[ChatMessage]) -> str | None:
        skill = None
        for message in history:
            text = message.text()
            if "Successfully switched to skill: `" in text:
                for line in text.split("\n"):
                    if "Successfully switched to skill: `" in line:
                        skill = line.replace(
                            "Successfully switched to skill: `", ""
                        ).replace("`", "")
        if skill not in list_skills().keys():
            skill = None
        logger.info(f"Active agent: `{skill}`")
        return skill

    def _make_skill_switch_tool(self, skill: Skill):
        async def _callback(**args: dict):
            if skill.name in list_skills().keys():
                logger.info(f"Successfully switched to skill: `{skill.name}`")
                return f"Successfully switched to skill: `{skill.name}`"
            else:
                logger.info(f"Failed to switch skill, unknown skill name: `{skill.name}`")
                return f"Failed to switch skill, unknown skill name: `{skill.name}`"

        return Tool(
            name=f"switch_skill.{skill.name}",
            description=f"Select the `{skill.name}` skill: {skill.description}",
            parameters={},
            tool_callable=_callback,
        )

    async def chat(self, messages: list[ChatMessage], output: OutputWriter, available_tools: List[Tool], **kwargs) -> bool:
        if "{today}" in self._system_prompt:
            kwargs["today"] = datetime.datetime.now().strftime("%A, %B %d, %Y")
        if "{now}" in self._system_prompt:
            kwargs["now"] = datetime.datetime.now().strftime("%A, %B %d, %Y, %H:%M:%S")
        system_prompt = self._system_prompt.format(**kwargs)

        # Create tools for switching skills
        skill_switch_tools = [self._make_skill_switch_tool(skill) for skill in list_skills().values()]

        # Create a copy of self._tools and extend it with skill.tools
        tool_filters = list(self._tools)
        selected_skill = self._determine_skill(messages)
        if selected_skill:
            skill = get_skill(selected_skill)
            if skill:
                system_prompt += f"\n\n{skill.prompt}"
                tool_filters.extend(skill.tools)
        tool_filters.extend(f"switch_skill.{skill_name}" for skill_name in self._skills)

        # Collect tools, filtering based on the extended_tools
        current_tools = [
            tool
            for tool in available_tools + skill_switch_tools
            if _tool_matches(tool.name, tool_filters)
            and tool.name != f"agent.{self._name}"
            and _tool_namespace_allowed(
                tool.name, available_tools, f"agent.{self._name}"
            )
        ]

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
                await output.default(chunk, separate=False)
            else:
                await output.thought(chunk, separate=False)

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
                await output.thought(f"Result:\n```\n{result}\n```")
            else:
                await output.thought(f"Failed parsing toolcall: `{tool_call}`")
                result = f"Failed parsing toolcall with error: `{tool_call}`."
                messages.append(ChatMessage(role="tool", content=result, tool_call_id=str(uuid.uuid4())))
                await output.thought(f"Result:\n```\n{tool_call}\n```")

        await output.default("", separate=False)

        # Exit if we did not call a tool, so we can return the flow to the user
        if len(response.tool_calls) == 0 and response.text.strip() != "":
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


def _tool_namespace_allowed(
    tool_name: str, available_tools: list[Tool], agent_name: str
) -> bool:
    # In all tools the tool with the `.__main__` closest to the tool_name defines
    # the namespace limitation, e.g. `agent.code.__main__`` limits the namespace to
    # `agent.code`, while `agent.code.agents.__main__` would limit the namespace to
    # `agent.code.agents` for a tool with the name `agent.code.agents.new-agent-writer`

    if tool_name.endswith(".__main__"):
        # __main__ tools are always allowed
        return True

    # Find the closest (longest) namespace from available tools that end with .__main__
    matched_namespace: str | None = None
    for t in available_tools:
        name = t.name
        if not name.endswith(".__main__"):
            continue
        ns = name[: -len(".__main__")]
        # ns matches tool_name if tool_name equals ns or starts with "ns."
        if tool_name.startswith(ns):
            if matched_namespace is None or len(ns) > len(matched_namespace):
                matched_namespace = ns

    # If no namespace restriction found, allow the tool
    if matched_namespace is None:
        return True

    # The agent must be within the matched namespace to be allowed
    return agent_name.startswith(matched_namespace)
