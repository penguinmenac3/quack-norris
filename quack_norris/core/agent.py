from typing import List, NamedTuple, Callable, Generator
import datetime
import yaml
import json

from quack_norris.micro_graph import Node, NodeResult, template_formatting
from quack_norris.core.llm import LLM, ChatMessage
from quack_norris.core.output_writer import OutputWriter


_TASK_PROMPT = """You are an expert at extracting the most recent user query or task from a chat.
* Your output should be a clear, specific, and standalone task to do.
* A task is a specific action or question that the user wants to be answered.
* If the user message is already a task, return it as is.
* If the user message is a question, return it as a question.
* If the user message is a request for information, return it as a question.
* If the user message is a command, return it as a command.
* If the latest message refers to previous messages, incorporate the necessary context so the task makes sense on its own.

<example>
What is the weather like in New York today?
</example>

<example>
Make the text more concise.
</example>

<example>
Book a flight to New York for tomorrow.
</example>
"""


_CONTEXT_PROMPT = """You are an expert at extracting context for a given task.
Typically tasks do not exist in a vacuum, but rather in the context of a chat history.
From the given chat history extract the context information that is needed to process the task.

If the task states to improve or change something, extract that thing.

<example>
Example Task: "Make the text more concise."
(You then find the text that is referenced and extract it and return it.)

Example Output:
It is with a careful observation and a desire to fully understand, that I feel compelled
to elaborate upon the rather complex phenomenon of noticing a vibrant shade of blue.
</example>

Task:
```
{task}
```
"""


_TOOL_CALLING_PROMPT = """## Tool Calling Instructions

One of your operation modes is to call tools.
If you decided to call a tool, you just do a tool call nothing else.
You can use the tools to perform actions or get information that is not available in the chat history.

You have access to the following tools:
<tools>
{tools}
</tools>

You can access the tools. Use them if you think they are suited for solving the task.
If you decide to invoke any of the function(s), you MUST put it in the format of
{{"name": function name, "parameters": dictionary of argument name and its value}}
You SHOULD NOT include any other text in the response if you call a function.
First print "[CALL] " and then a json object specifying the tool call you want to make.

<example>
[CALL] {{"name": "tool_name", "parameters": {{"argument1": "value1", "argument2": "value2"}}}}
</example>
"""


class Tool(NamedTuple):
    name: str
    description: str
    arguments: str
    tool_callable: Callable | Node


class Agent(Node):
    def __init__(
        self,
        llm: LLM,
        model: str,
        prompt: str,
        tools: List[Tool] | None = None,
        output: str = "default",
        context_name: str = "context",
        max_retries: int = 0,
        max_loops: int = -1,
        no_think=False,
    ):
        super().__init__(max_retries=max_retries)
        self._llm = llm
        self._model = model
        self._output = output
        self._context_name = context_name
        self._query_prompt = _TASK_PROMPT
        self._context_prompt = _CONTEXT_PROMPT
        self._tool_calling_prompt = _TOOL_CALLING_PROMPT
        self._raw_prompt = prompt
        self._no_think = no_think
        self.set_tools(tools, max_loops)

    def set_tools(self, tools: List[Tool] | None, max_loops: int = -1):
        system_prompt, name, description, filtered_tools = self._parse_prompt(self._raw_prompt, tools or [])
        self._system_prompt = system_prompt
        self.name = name
        self.description = description
        self._tools = filtered_tools
        if max_loops < 0:
            max_loops = 1 if len(self._tools) > 0 else 0  # We need to allow 1 loop for tool calling
        self._max_loops = max_loops

    def _parse_prompt(self, prompt: str, tools: List[Tool]) -> tuple[str, str, str, List[Tool]]:
        parts = prompt.split("---")
        if len(parts) < 3 or parts[0].strip() != "":
            return prompt, str(self.__class__), str(self.__doc__), tools
        system_prompt = "---".join(parts[2:]).strip()
        meta = parts[1]
        yaml_meta = yaml.safe_load(meta)
        name = yaml_meta.get("name", "Agent").strip()
        description = yaml_meta.get("description", "An agent that can process user queries and provide answers.").strip()
        if "tools" in yaml_meta:
            tool_filters = yaml_meta.get("tools", "")
            tool_filters = [t.strip() for t in tool_filters.split(",")]
            tools = [
                tool
                for tool in tools
                if self._matches(tool.name, tool_filters)
            ]
        else:
            tools = []
        return system_prompt, name, description, tools

    def _matches(self, tool_name: str, tool_filters: list[str]) -> bool:
        for filter_str in tool_filters:
            if tool_name == filter_str:
                return True
            if filter_str.endswith("*") and tool_name.startswith(filter_str[:-1]):
                return True
        return False

    def as_tool(self) -> Tool:
        if "{task}" in self._system_prompt:
            task = "  - task: The task to process. If not provided, the agent will extract the task from the chat history.\n"
        else:
            task = ""
        if "{" + self._context_name + "}" in self._system_prompt:
            ctx = f"  - {self._context_name}: The context to use for the task. If not provided, the agent will extract the context from the chat history.\n"
        else:
            ctx = ""
        return Tool(
            name="agent." + self.name,
            description=self.description,
            arguments=(task + ctx).strip("\n"),
            tool_callable=self
        )

    def _get_task(self, shared: dict) -> str:
        prompt = self._query_prompt
        messages = shared["chat_messages"]
        return self._llm.chat(self._model, messages[-3:] + [ChatMessage(role="user", content=prompt)]).strip()

    def _get_context(self, task: str, shared: dict) -> str:
        messages = shared["chat_messages"]
        if len(messages) <= 2:
            return ""
        prompt = self._context_prompt.format(task=task)
        return self._llm.chat(self._model, messages[-3:] + [ChatMessage(role="user", content=prompt)]).strip()

    def _build_tool_prompt(self) -> str:
        tool_descriptions = []
        for tool in self._tools:
            description = tool.description
            if description.endswith("."):
                description = description[:-1]
            tool_descriptions.append(
                f"* {tool.name.lower()}: {description}.\n{tool.arguments}".strip()
            )
        tools = "\n".join(tool_descriptions)
        return self._tool_calling_prompt.format(tools=tools)

    async def _call_tool(self, tool_call: str, shared: dict) -> str:
        try:
            spec = json.loads(tool_call)
            tool_name = spec["name"]
            args = spec["parameters"]
            for tool in self._tools:
                if tool.name.lower() == tool_name:
                    if isinstance(tool.tool_callable, Node):
                        result = await tool.tool_callable.start(shared, **args)
                        if result is not None and "content" in result:
                            return result["content"]
                        else:
                            return str(result)
                    elif isinstance(tool.tool_callable, Callable):
                        result = tool.tool_callable(args)
                        if hasattr(result, '__await__'):  # Await async tool calls
                            result = await result
                        return result
            return f"Tool '{tool_name}' not found."
        except Exception as e:
            return f"Error calling tool: {e}"

    async def run(self, shared: dict, **kwargs) -> NodeResult:
        writer = OutputWriter.get_writer(shared)
        is_agent_mode = "task" in kwargs and kwargs["task"] != ""

        # Prepare fields to fill in prompt: task, context, tools, today/now
        args = {}
        if "{task}" in self._system_prompt:
            args["task"] = kwargs["task"] if is_agent_mode else self._get_task(shared)
        if "{" + self._context_name + "}" in self._system_prompt:
            args[self._context_name] = (
                kwargs[self._context_name]
                if self._context_name in kwargs
                else self._get_context(args.get("task", ""), shared)
            )
        if "{today}" in self._system_prompt:
            args["today"] = datetime.datetime.now().strftime("%A, %B %d, %Y")
        if "{now}" in self._system_prompt:
            args["today"] = datetime.datetime.now().strftime("%A, %B %d, %Y, %H:%M:%S")

        tool_prompt = self._build_tool_prompt() if len(self._tools) > 0 else ""

        # Prepare loop variables, they might be modified during the loop temporarily
        if "task" in args and self._context_name in args:
            messages: List[ChatMessage] = list()  # If we have context and task, do not pass chat history
        else:
            messages: List[ChatMessage] = list(shared["chat_messages"])
        system_prompt = self._system_prompt

        # Run in a loop, loop when we
        for i in range(self._max_loops + 1):
            prompt = template_formatting(system_prompt, shared, **args)
            if i < self._max_loops and tool_prompt != "":
                prompt += "\n\n" + tool_prompt  # Add tool prompt except in last round
            if self._no_think:
                prompt += " /no_think"  # Add /no_think to turn of thinking
            history = [ChatMessage(role="system", content=prompt)] + messages
            if is_agent_mode:
                # If we are a subagent use the chat (w/o streaming) and fake stream,
                # this way we have less overhead in our api call
                stream = to_stream(self._llm.chat(model=self._model, messages=history))
            else:
                stream = self._llm.chat_stream(model=self._model, messages=history)

            answer = ""
            is_tool_call = False
            is_thinking = False
            for word in to_word_stream(stream):
                if "<think>" in word:
                    is_thinking = True
                if "</think>" in word:
                    is_thinking = False
                    word = word[len("</think>") :].strip()
                if not is_thinking and word.startswith("[CALL]"):
                    is_tool_call = True
                    word = word[len("[CALL]") :].strip()
                if not is_thinking:
                    answer += word  # Only add non thoughts to the answer (history and tool call)
                if not is_tool_call and not is_agent_mode:
                    if is_thinking:
                        await writer.thought(word, end="")
                    else:
                        await writer.write(word, message_type=self._output)
            if not is_agent_mode:
                # Add a new line after we finished streaming
                await writer.write("\n", message_type=self._output)

            if is_tool_call:
                tool_call = answer.strip()
                await writer.thought(f"Calling Tool: `{tool_call}`")
                result = await self._call_tool(tool_call, shared)
                messages.append(ChatMessage(role="assistant", content=f"[CALL] {tool_call}"))
                messages.append(ChatMessage(role="tool", content=result))
                await writer.thought(f"Tool Result:\n\n```\n{result}\n```\n")
                await writer.write("", message_type=self._output)  # Break thought message
            else:
                if is_agent_mode:
                    await writer.thought(f"Agent `{self.name}` responded.")
                return {"role": "assistant", "content": answer}


def to_word_stream(stream: Generator[str, None, None]) -> Generator[str, None, None]:
    word: str = ""
    for token in stream:
        for char in token:
            word += char
            # Yield after appending, so the whitespacespace is at end of word included
            if char in [" ", "\n", "\t"]:
                yield word
                word = ""
    if word != "":
        yield word


def to_stream(answer: str) -> Generator[str, None, None]:
    for letter in answer:
        yield letter
