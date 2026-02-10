from quack_norris.api.chat_handler import ChatHandler
from typing import AsyncGenerator, Optional
import datetime
import uuid

from quack_norris.logging import logger
from quack_norris.core.llm.types import Tool, ToolCall, ChatMessage
from quack_norris.core.llm.model_provider import ModelProvider
from quack_norris.core.tools.tool import list_tools
from quack_norris.core.agents.skill import list_skills, find_skill


class Agent(ChatHandler):
    def __init__(
        self,
        system_prompt: str,
        model: str,
        description: str,
        max_steps: int,
        tools: list[str] = [],
        skills: list[str] = [],
    ):
        self._system_prompt = system_prompt
        self._model = model
        self._description = description
        self._max_steps = max_steps
        self._tools = tools
        self._skills = skills

    async def __call__(
        self,
        history: list[ChatMessage],
        workspace: str,
        additional_tools: list[Tool] = [],
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        for step in range(self._max_steps):
            if "{today}" in self._system_prompt:
                kwargs["today"] = datetime.datetime.now().strftime("%A, %B %d, %Y")
            if "{now}" in self._system_prompt:
                kwargs["now"] = datetime.datetime.now().strftime("%A, %B %d, %Y, %H:%M:%S")
            system_prompt = self._system_prompt.format(**kwargs)
            skills = list_skills(self._skills)
            skill = find_skill(history[-1].text(), skills)
            if skill is not None:
                system_prompt += f"\n\n{skill.description}\n"
            additional_tools = self._filter_tools(additional_tools, skill)
            if step == self._max_steps - 1:
                additional_tools = []  # No tools on last step

            # Add limitations to agent what it does and encourage handover
            system_prompt += "\n\n## Final Remarks\n"
            system_prompt += "* You are an expert in your field and only answer questions related to your expertise and role.\n"
            if len(additional_tools) > 0:
                system_prompt += "* If the user asks something outside your expertise, hand it over to another agent.\n"
                system_prompt += "* If you do not know the right agent, `agent.auto` will be able to route it or handle the request.\n"
                system_prompt += "* You have skills, which give you information on how to do things better. You can always have one skill active. Make use of it.\n"
                system_prompt += (
                    "* Additionally, you can have access to tools to help you with your job.\n"
                )
            system_prompt += "* If you cannot answer a question, because it does not fit to your role and you cannot give it to another agent. Let the user politely know."

            # Send request to LLM
            llm = ModelProvider.get_llm(self._model)
            response = llm(
                messages=history[-10:],  # only pass last 10 messages to AI
                tools=additional_tools,
                system_prompt=system_prompt,
                stream=True,
            )

            # Stream the response
            for chunk in response.stream:
                yield chunk

            # Add the response to the history
            history.append(
                ChatMessage(role="assistant", content=response.text, tool_calls=response.tool_calls)
            )

            # Process tool calls and add their results to the history
            for tool_call in response.tool_calls:
                if isinstance(tool_call, ToolCall):
                    yield f"Calling Tool: `{tool_call.tool.name}` with params `{tool_call.params}`\n"
                    result = tool_call.tool.tool_callable(**tool_call.params)
                    if hasattr(result, "__await__"):  # Await async tool calls
                        result = await result
                    result = str(result)
                    history.append(
                        ChatMessage(role="tool", content=result, tool_call_id=tool_call.id)
                    )
                    yield f"Result:\n```\n{result}\n```\n"
                else:
                    yield f"Failed parsing toolcall: `{tool_call}`\n"
                    result = f"Failed parsing toolcall with error: `{tool_call}`."
                    history.append(
                        ChatMessage(role="tool", content=result, tool_call_id=str(uuid.uuid4()))
                    )
                    yield f"Result:\n```\n{tool_call}\n```\n"

            yield "\n"

            # Exit if we did not call a tool, so we can return the flow to the user
            if len(response.tool_calls) == 0 and response.text.strip() != "":
                logger.info("Exiting runner: No tool call!")
                return

    def _filter_tools(self, tools, skill):
        def _tool_matches(tool_name: str, tool_filters: list[str]) -> bool:
            for filter_str in tool_filters:
                if tool_name == filter_str:
                    return True
                if filter_str.endswith("*") and tool_name.startswith(filter_str[:-1]):
                    return True
            return False

        tools = tools.copy() + list_tools()
        tool_filters = []
        if self._tools:
            tool_filters += self._tools
        if skill is not None and skill.tools:
            tool_filters += skill.tools
        if len(tool_filters) == 0:
            return tools
        return [tool for tool in tools if _tool_matches(tool.name, tool_filters)]


# Registry
_agents: dict[str, Agent] = {}


def list_agents(names_or_partials: list[str] | None = None) -> dict[str, Agent]:
    """List all agents in the registry."""
    if names_or_partials is None:
        return _agents
    return {name: _agents[name] for name in names_or_partials if name in _agents}


def get_agent(name: str) -> Optional[Agent]:
    """Retrieve a skill by name."""
    return _agents.get(name)


def find_agent(query: str, agents: dict[str, Agent]) -> Optional[Agent]:
    """Find an agent by name or description matching the query."""
    query_lower = query.lower()
    for name, agent in agents.items():
        if query_lower in name.lower() or query_lower in agent._description.lower():
            return agent
    return None


def update_agent(name: str, agent: Agent):
    """Update or add an agent to the registry."""
    _agents[name] = agent


def remove_agent(name: str):
    """Remove an agent from the registry."""
    del _agents[name]
