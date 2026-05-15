# Lesson C — Putting Prefab Inside MCP

Until now, every MCP tool we wrote returned **text**. `reverse_string("rohan")` gave back `"nahor"`. `read_file("x.txt")` gave back the file contents. The client had to decide what to do with the string — usually, paste it into the chat.

That is about to change. In this lesson, an MCP tool will return **a UI**. Not a description of a UI, not a plan for a UI. An actual, rendered, clickable card that shows up inside the chat host (Claude Desktop, or any MCP client that speaks Prefab).

The agent will not tell you about the result. The agent will *hand you an app*.

## What we need installed

```bash
pip install prefab-ui fastmcp
```

Two pieces:

- **`prefab-ui`** — the thing that draws pages (we already used it in A and B).
- **`fastmcp`** — a small MCP server library that knows how to return Prefab UIs from tools. It is the same flavour of FastMCP we have been using, just the standalone package that Prefab's integration hooks into.

## The one new idea: `@mcp.tool(app=True)`

In Session 3 and 4 so far, you wrote tools like this:

```python
@mcp.tool()
def reverse_string(text: str) -> str:
    return text[::-1]
```

The return type was a string. Prefab gives us one tiny addition:

```python
@mcp.tool(app=True)
def status_card() -> PrefabApp:
    with PrefabApp(...) as app:
        H3("Today's status")
        Text("All systems nominal.")
    return app
```

Two differences, both small:

1. The decorator is `@mcp.tool(app=True)` — that flag tells FastMCP "this tool returns a UI, not a string."
2. The return value is a `PrefabApp`, built with the same `with` blocks from Lesson A.

That is the whole integration. Everything else you already know.

## Read the code, then run it

Open [server.py](server.py). You will see two tools:

- `status_card()` — a static card. No interactivity. Just proves a tool can return a rendered UI.
- `counter_card()` — the exact counter you built in Lesson B, now returned from a tool call. Click the button inside the host. The number goes up. A tool call returned an interactive app.

Run it the fastest way — this opens a browser preview that lets you click the tools and see the UI they return:

```bash
fastmcp dev apps server.py
```

This is FastMCP's **Prefab-aware** dev previewer (`apps` = "preview FastMCPApp UIs"). It is different from `fastmcp dev inspector`, which is the plain JSON-tool inspector you would use for a text-returning server.

Click `status_card`. The card renders. Click `counter_card`. The counter renders, and the Increment button actually works.

To use the server from a real MCP host (Claude Desktop, etc.), run the server directly:

```bash
uv run server.py
```

and register it in the host's MCP config. In Claude Desktop you can then say *"show me today's status"* and the card appears in chat. Say *"give me a counter I can click"* and the counter comes back — clickable, inside the conversation.

## Why this is a bigger deal than it looks

Stay with me for the payoff.

A normal MCP tool is a function call. You ask a question, the model picks a tool, you get text back. The conversation is the app. The tool is support staff.

A Prefab MCP tool is a function call that **returns a screen**. The model picks a tool, and the *output of that call is itself interactive*. You can click. The click fires a `SetState`. The state changes. The screen updates — *inside the chat window*.

The agent has stopped being a chat buddy. The agent is now a **loader of small apps, built on demand**. Each one is a Prefab `with` block. Each one is three lines of Python wrapped in a tool. And because the tool signature is still just a normal Python function, **the LLM can write more of them.**

That last sentence is the bridge to Lesson D. Hold onto it.

## What to experiment with

1. Add a third tool `@mcp.tool(app=True)` called `hello_card(name: str)` that returns a card greeting the person by name. Notice the name is just a normal Python function argument — no MCP magic, no Prefab magic.
2. Inside `counter_card`, change the step from 1 to 10. Reload. Call the tool again. The new version renders. You edited a tool, the agent's next call picked up the change.
3. Add a second button to `counter_card` that resets the counter. Same `SetState` pattern as Lesson B.

## Ready check

1. What one flag on `@mcp.tool(...)` tells FastMCP that a tool returns a UI instead of text?
2. What object does such a tool return?
3. Looking at `counter_card`, which parts are "Prefab stuff" and which parts are "MCP stuff"? Can you point at the seam?

If you can point at that seam cleanly — the `with PrefabApp(...)` block is Prefab, the `@mcp.tool(app=True)` is MCP, and nothing else crosses over — you are ready for Lesson D, where the agent itself writes new Prefab UIs on demand and turns them into apps.
