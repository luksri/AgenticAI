"""
Lesson C — an MCP server whose tools return Prefab UIs.

Read the README.md next to this file first. Then run:

    uv run server.py
    # or:
    fastmcp dev server.py

Point your MCP host (Claude Desktop, FastMCP inspector, etc.) at this server.
Ask the agent to "show today's status" — a card renders inside the chat.
Ask for "a counter I can click" — an interactive counter comes back.

What to notice:
  - The ONLY new idea vs the Session 4 MCP server is `@mcp.tool(app=True)`
    and returning a PrefabApp instead of a string.
  - Everything inside `with PrefabApp(...)` is the exact Prefab DSL from
    Lessons A and B. Nothing new there.
"""

from datetime import date

from fastmcp import FastMCP
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Column,
    H1,
    H3,
    Muted,
    Text,
)
from prefab_ui.actions import SetState
from prefab_ui.rx import Rx


mcp = FastMCP("PrefabTeachingServer")


@mcp.tool(app=True)
def status_card() -> PrefabApp:
    """Show a simple status card for today."""
    with PrefabApp(css_class="max-w-md mx-auto") as app:
        with Card():
            with CardHeader():
                CardTitle("Today's status")
            with CardContent():
                with Column(gap=2):
                    H3(f"{date.today().isoformat()}")
                    Text("All systems nominal.")
                    Muted("Rendered from an MCP tool — not from a prose reply.")
    return app


@mcp.tool(app=True)
def counter_card() -> PrefabApp:
    """Return an interactive counter that the user can click."""
    count = Rx("count")

    with PrefabApp(state={"count": 0}, css_class="max-w-md mx-auto") as app:
        with Card():
            with CardHeader():
                CardTitle("Counter")
            with CardContent():
                with Column(gap=4):
                    H1(f"{count}")
                    Button(
                        "Increment",
                        on_click=SetState("count", "{{ count + 1 }}"),
                    )
    return app


if __name__ == "__main__":
    mcp.run()
