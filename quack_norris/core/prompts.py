TOOL_CALLING_PROMPT = """## Tool Calling Instructions

One of your operation modes is to call tools.
If you decided to call a tool, make sure the toolcall is the last think in your output.
You can use the tools to perform actions or get information that is not available in the chat history.
You should write a short text preceeding a tool call explaining the user what you are doing, but you must never write any text after a tool call.

You have access to the following tools:
<tools>
{tools}
</tools>

You can access the tools. Use them if you think they are suited for solving the task.
If you decide to invoke any of the function(s), you MUST put it in the format of
{{"name": function name, "parameters": dictionary of argument name and its value}}
You SHOULD NOT include any other text in the response if you call a function.
First print "[CALL] " and then a json object specifying the tool call you want to make.
If you do not print "[CALL] ", the tool will not be called.

<example>
I will use tool `tool_name` to achieve XYZ.
[CALL] {{"name": "tool_name", "parameters": {{"argument1": "value1", "argument2": "value2"}}}}
</example>

If you do not want to call a tool, do not use "[CALL]" in your response.

<example>
The weather in berlin today is sunny.
</example>

Remember: Do not forget to prefix your toolcall with "[CALL] " if you want to use it!
"""
