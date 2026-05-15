"""
Tiny MCP server exposing two tools: add and subtract.

Run standalone for a sanity check:
    python mcp_server.py
The agent in agent.py launches this file as a subprocess over stdio.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calc-server")


@mcp.tool()
def add(a: float, b: float) -> float:
    """Return a + b."""
    return a + b


@mcp.tool()
def subtract(a: float, b: float) -> float:
    """Return a - b."""
    return a - b


if __name__ == "__main__":
    mcp.run(transport="stdio")
