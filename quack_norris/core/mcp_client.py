from typing import Literal
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport, SSETransport, StdioTransport

from quack_norris.core.agent import Tool


class MCPClient:
    def __init__(
        self,
        type: Literal["http", "sse", "stdio"],
        url: str = "",
        command: str = "",
        args: list[str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if type == "http":
            if url == "":
                raise ValueError("URL must be provided for HTTP mode.")
            transport = StreamableHttpTransport(url, headers=headers)
        elif type == "sse":
            if url == "":
                raise ValueError("URL must be provided for HTTP mode.")
            transport = SSETransport(url, headers=headers)
        elif type == "stdio":
            if command == "":
                raise ValueError("Command must be provided for STDIO mode.")
            if args is None:
                args = []
            transport = StdioTransport(command, args)
        else:
            raise ValueError(f"Unsupported transport type `{type}` for MCPClient.")
        self._client = Client(transport=transport)

    async def list_tools(self, prefix: str = "") -> list[Tool]:
        async with self._client:
            tools = await self._client.list_tools()
            return [
                Tool(
                    name=prefix + tool.name,
                    description=tool.description or "missing description",
                    arguments=str(tool.inputSchema or "missing arguments definition"),
                    tool_callable=self._make_callable(tool.name),
                )
                for tool in tools
            ]

    def _make_callable(self, tool_name):
        async def _call_tool(args: dict) -> str:
            async with self._client:
                try:
                    result = await self._client.call_tool(name=tool_name, arguments=args)
                    out = ""
                    for content in result.content:
                        if content.type == "text":
                            out += content.text
                    return out
                except Exception as e:
                    return f"Error calling tool {tool_name}: {str(e)}"

        return _call_tool
