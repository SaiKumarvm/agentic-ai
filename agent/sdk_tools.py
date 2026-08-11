"""Adapts our framework-agnostic tools (agent/tools/) for the Claude Agent SDK.

The Agent SDK's custom-tool mechanism differs from the raw Messages API tool
schema used in agent/tools/: it wants an async function decorated with
@tool, registered on an in-process MCP server. This file is the only place
that translation happens — each tool's actual logic is reused unchanged
from agent/tools/, so the same tool works under either backend.
"""

from claude_agent_sdk import create_sdk_mcp_server, tool

from .tools import calculator, get_current_time, random_number

# The key used in ClaudeAgentOptions.mcp_servers={...}. The SDK exposes each
# tool to Claude under the name f"mcp__{MCP_SERVER_NAME}__{tool_name}", which
# is what has to go in allowed_tools to pre-approve it.
MCP_SERVER_NAME = "local_tools"


@tool("calculator", calculator.SCHEMA["description"], {"expression": str})
async def calculator_tool(args: dict) -> dict:
    result = calculator.run(args["expression"])
    return {
        "content": [{"type": "text", "text": result}],
        "is_error": result.startswith("Error"),
    }


@tool("get_current_time", get_current_time.SCHEMA["description"], {})
async def get_current_time_tool(args: dict) -> dict:
    return {"content": [{"type": "text", "text": get_current_time.run()}]}


@tool(
    "random_number",
    random_number.SCHEMA["description"],
    {"minimum": int, "maximum": int},
)
async def random_number_tool(args: dict) -> dict:
    result = random_number.run(minimum=args["minimum"], maximum=args["maximum"])
    return {
        "content": [{"type": "text", "text": result}],
        "is_error": result.startswith("Error"),
    }


SERVER = create_sdk_mcp_server(
    name=MCP_SERVER_NAME,
    tools=[calculator_tool, get_current_time_tool, random_number_tool],
)

ALLOWED_TOOL_NAMES = [
    f"mcp__{MCP_SERVER_NAME}__{calculator.NAME}",
    f"mcp__{MCP_SERVER_NAME}__{get_current_time.NAME}",
    f"mcp__{MCP_SERVER_NAME}__{random_number.NAME}",
]
