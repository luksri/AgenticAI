# Lesson E — Interactive Talk-to-App

Welcome to the future. 

In Lesson D, you saw how an LLM could generate a whole dashboard from a single sentence. But it had two big flaws:
1. **It was transient**: Refresh the page, and your changes were gone.
2. **It was terminal-bound**: You had to go back to your IDE to change the app.

This lesson fixes both. 

## The Architecture

Instead of a standalone script, we now have an **MCP Server**. The UI is no longer a static `.py` file on disk; it is a **dynamic response** from an MCP tool.

```
  browser UI           CallTool           MCP Server          SQLite + Gemini
  ───────────   ───► update_app  ───►    ──────────    ───►  ───────────────
  (type prompt)        (prompt)           (server.py)         (persist & think)
```

## How to Run

1. Make sure your `.env` has `GEMINI_API_KEY`.
2. Run the server:
   ```bash
   uv run server.py
   # or
   fastmcp dev inspector server.py
   ```
3. Open your MCP host (Claude Desktop or the FastMCP inspector).
4. Run the `dashboard` tool.

## What to try

1. **Persistent State**: Type `"Add a 'Tasks' tab with a checklist of 3 items"` in the browser input and hit **Update App**. Then refresh the page. The tab is still there because it's saved in `dashboard.db`.
2. **Server-Side Interactivity**: Tick one of the checkboxes in your new "Tasks" tab. Notice that the UI stays in sync. Every click calls a `toggle_checklist_item` tool on the server that updates the JSON spec in SQLite.
3. **Complex Evolutions**: Type `"Add a radar chart of my productivity across Focus, Email, Meetings, and Coding"`. The app morphs instantly without you ever leaving the browser.

## Why this matters

This isn't just a "dashboard generator" anymore. It's a **self-evolving internal tool**. You can build it, use it, and change it while using it. The "code" is just a piece of data (the JSON spec) and a renderer that knows how to turn it into pixels.
