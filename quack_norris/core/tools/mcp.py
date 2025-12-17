from typing import Literal, Any
import asyncio
import subprocess
import sys
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport, SSETransport, StdioTransport

from quack_norris.logging import logger
from quack_norris.core.llm.types import Tool


async def initialize_mcp_tools(mcp_configs: dict[str, Any], builtins: bool = True) -> list[Tool]:
    if builtins:
        mcp_configs["filesystem"] = {
            "type": "http",
            "url": "http://127.0.0.1:13370/mcp/",
            "command": "quack-norris-fs",
            "args": []
        }
    # load tools from MCP servers
    tools: list[Tool] = []
    logger.info("Connecting to MCPs")
    tasks = []
    for name, mcp_config in mcp_configs.items():
        name = (
            name.replace("-", "_")
            .replace("/", "_")
            .replace(".", "_")
            .replace("(", "_")
            .replace(")", "_")
        )
        client = MCPClient(**mcp_config)
        tasks.append(client.list_tools(prefix=f"{name}."))
    for result in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(result, Exception):
            logger.warning(f"Failed to gather tools from MCP for reason: {result}")
        else:
            tools.extend(result)  # type: ignore

    logger.info("MCP Tools Discovered")
    for tool in tools:
        logger.info(f"* {tool.name}: {tool.description}")
    logger.info(f"Connected {len(tools)} tools")
    return tools


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
        self._url = url
        self._command = command
        self._args = args

    async def list_tools(self, prefix: str = "") -> list[Tool]:
        try:
            return await self._try_listing_tools(prefix)
        except RuntimeError:
            logger.warning(f"Failed to connect to: {self._url}")
        if self._command:
            try:
                logger.info(
                    f"Attempting to start: {self._command} {' '.join(self._args or [])}"
                )
                subprocess.Popen(
                    [self._command] + (self._args or []),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    shell=sys.platform == "win32",
                    close_fds=True,
                )
                await asyncio.sleep(5)
            except Exception as e:
                logger.warning(f"Failed to start background process: {e}")

        return await self._try_listing_tools(prefix)

    async def _try_listing_tools(self, prefix: str = "") -> list[Tool]:
        async with self._client:
            tools = await self._client.list_tools()
            return [
                Tool(
                    name=prefix + tool.name,
                    description=tool.description or "missing description",
                    parameters=tool.inputSchema["properties"],
                    tool_callable=self._make_callable(tool.name),
                )
                for tool in tools
            ]

    def _make_callable(self, tool_name):
        async def _call_tool(**kwargs: dict) -> str:
            async with self._client:
                try:
                    result = await self._client.call_tool(name=tool_name, arguments=kwargs)
                    out = ""
                    for content in result.content:
                        if content.type == "text":
                            out += content.text
                    return out
                except Exception as e:
                    return f"Error calling tool {tool_name}: {str(e)}"

        return _call_tool
