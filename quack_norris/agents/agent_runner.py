import os
import datetime
import dotenv

from quack_norris.agents.agent_definition import AgentDefinition
from quack_norris.core.llm import LLM, ChatMessage, Tool, ToolCall
from quack_norris.core.output_writer import OutputWriter


class AgentRunner:
    def __init__(
        self,
        llm: LLM,
        default_agent: str,
        agents: dict[str, AgentDefinition],
        tools: list[Tool],
        max_steps: int = 5,
    ):
        self._llm = llm
        self._default_agent = default_agent
        self._agents = agents
        self._tools = tools
        self._max_steps = max_steps

    def _determine_agent(self, history: list[ChatMessage], agent: str) -> str:
        agent = self._default_agent
        for message in history:
            text = message.text()
            if "Successfully switched to agent: `" in text:
                for line in text.split("\n"):
                    if "Successfully switched to agent: `" in line:
                        agent = line.replace("Successfully switched to agent: `", "").replace("`", "")
        if agent not in self._agents.keys():
            agent = self._default_agent
        print(f"Active agent: `{agent}`")
        return agent

    async def process_request(
        self, history: list[ChatMessage], output: OutputWriter, agent_name: str = ""
    ) -> None:
        tools = list(self._tools)  # copy so we can locally modify

        # Allow switching of agent during conversation, if no agent is provided
        if agent_name == "":

            def _switch_tool(agent: str):
                async def _callback(args: dict):
                    if agent in self._agents.keys():
                        shared["agent"] = agent
                        shared["task"] = args["task"] if "task" in args else ""
                        context_name = self._agents[agent].context_name
                        shared[context_name] = args[context_name] if context_name in args else ""
                        print(f"Successfully switched to agent: `{agent}`")
                        return f"Successfully switched to agent: `{agent}`"
                    else:
                        print(f"Failed to switch agent, unknown agent name: `{agent}`")
                        return f"Failed to switch agent, unknown agent name: `{agent}`"

                return _callback

            agent_name = self._determine_agent(history, agent_name)
            tools += [agent._as_tool(_switch_tool(key)) for key, agent in self._agents.items()]

        dotenv.load_dotenv()
        default_model = os.environ.get("MODEL", "AUTODETECT")
        if default_model == "AUTODETECT":
            default_model = os.environ.get("DEFAULT_MODEL", "gemma3:12b")
        is_system_prompt_last = os.environ.get("SYSTEM_PROMPT_LAST", False) in [True, "true", "1", "yes", "on"]

        shared = {"chat_messages": history, "agent": agent_name, "task": ""}
        for step in range(max(self._max_steps, 1)):
            # Prepare the system prompt
            agent = self._agents[shared["agent"]]
            args = dict(shared)
            args["task"] = args["task"] if "task" in args else ""
            args[agent.context_name] = args[agent.context_name] if agent.context_name in args else ""
            if "{today}" in agent.system_prompt:
                args["today"] = datetime.datetime.now().strftime("%A, %B %d, %Y")
            if "{now}" in agent.system_prompt:
                args["now"] = datetime.datetime.now().strftime("%A, %B %d, %Y, %H:%M:%S")
            system_prompt = agent.system_prompt.format(**args)

            # Collect tools
            current_tools = [
                tool
                for tool in tools
                if _matches(tool.name, agent.tool_filters) and tool.name != f"agent.{agent.name}"
            ]
            # print(f"Tools (all) {[tool.name for tool in tools]}")
            # print(f"Tools (current) {[tool.name for tool in current_tools]}")

            # Send request to LLM
            response = self._llm.chat_stream(
                model=agent.model if agent.model != "" else default_model,
                messages=shared["chat_messages"][-10:], # only pass last 10 messages to AI
                tools=current_tools if step < self._max_steps - 1 else [],
                system_prompt=system_prompt,
                no_think=agent.no_think,
                system_prompt_last=agent.system_prompt_last if agent.model != "" else is_system_prompt_last,
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
            shared["chat_messages"].append(ChatMessage(role="assistant", content=response.text))

            # Process tool calls and add their results to the history
            for tool_call in response.tool_calls:
                if isinstance(tool_call, ToolCall):
                    await output.thought(
                        f"Calling Tool: `{tool_call.tool.name}` with params `{tool_call.params}`"
                    )
                    result = tool_call.tool.tool_callable(tool_call.params)
                    if hasattr(result, "__await__"):  # Await async tool calls
                        result = await result
                    result = str(result)
                    shared["chat_messages"].append(ChatMessage(role="tool", content=result))
                    await output.thought(f"Result:\n\n```\n{result}\n```\n")
                else:
                    await output.thought(f"Failed parsing toolcall: `{tool_call}`")
                    result = f"Failed parsing toolcall with error: `{tool_call}`."
                    shared["chat_messages"].append(ChatMessage(role="assistant", content=result))
                    await output.thought(f"Result:\n\n```\n{tool_call}\n```\n")

            await output.default("")

            # Exit if we did not call a tool, so we can return the flow to the user
            if len(response.tool_calls) == 0:
                print("Exiting runner: No tool call!")
                return


def _matches(tool_name: str, tool_filters: list[str]) -> bool:
    for filter_str in tool_filters:
        if tool_name == filter_str:
            return True
        if filter_str.endswith("*") and tool_name.startswith(filter_str[:-1]):
            return True
    return False
