from typing import Callable
from quack_norris.core.llm.types import Tool, ToolParameter
import inspect


_TOOLS = {}

def register_tool(name: str) -> Callable:
    """Registers a function as a tool with the given name. Spec is inferred from the function signature."""
    def wrapper(func: Callable) -> Callable:
        description = func.__doc__ or "No description provided."
        parameters: dict[str, ToolParameter] = {}
        sig = inspect.signature(func)
        for param in sig.parameters.values():
            if param.name == "return" or param.name == "self":
                continue
            param_dict: ToolParameter = {
                "type": param.annotation.__name__ if hasattr(param.annotation, "__name__") else str(param.annotation)
            }
            if param.default is not inspect.Parameter.empty:
                param_dict["default"] = param.default
            parameters[param.name] = param_dict

        # Handle methods inside classes
        if hasattr(func, "__func__"):
            def bound_method_wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            tool_callable = bound_method_wrapper
        else:
            tool_callable = func

        _TOOLS[name] = Tool(
            name=name,
            description=description,
            parameters=parameters,
            tool_callable=tool_callable
        )
        return func
    
    return wrapper


def list_tools() -> list[Tool]:
    """Lists all registered tools."""
    return list(_TOOLS.values())


def get_tool(name: str) -> Tool:
    """Retrieves a registered tool by its name."""
    return _TOOLS[name]


def search_tools(query: str) -> list[Tool]:
    """Search for tools matching the given query string."""
    results = []
    for tool in _TOOLS.values():
        # TODO make this fancier with embeddings or something smarter
        if query.lower() in tool.name.lower() or query.lower() in tool.description.lower():
            results.append(tool)
    return results


if __name__ == "__main__":
    # Example usage
    @register_tool(name="example_tool")
    def example_tool(param1: str, param2: int = 42) -> str:
        """An example tool that does something."""
        return f"param1: {param1}, param2: {param2}"

    class ExampleClass:
        @register_tool(name="class_tool")
        def class_tool(self, param1: str, param2: int = 42) -> str:
            """A class method tool example."""
            return f"Class method - param1: {param1}, param2: {param2}"

    example_instance = ExampleClass()

    print("Registered Tools:")
    for tool in list_tools():
        print(f"- {tool.name}: {tool.description}")
        print(f"  Parameters: {tool.parameters}")

    # Test the tools
    print(_TOOLS["example_tool"].tool_callable("test", 123))
    print(_TOOLS["class_tool"].tool_callable(example_instance, "test", 123))
