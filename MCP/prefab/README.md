# Prefab Track — from UI basics to "Talk-to-App"

Five short lessons. Each one has a `README.md` you read first, then the code. Work through them in order.

| # | Folder | What you learn |
|---|---|---|
| 0 | [`00_prelesson/`](00_prelesson/) | The four ideas every UI framework is built on, via a tiny terminal counter. |
| A | [`01_hello_prefab/`](01_hello_prefab/) | The Prefab DSL — describe a static page with nested `with` blocks. |
| B | [`02_state_and_events/`](02_state_and_events/) | `Rx` state and `SetState` actions — the Tkinter counter, rebuilt in Prefab. |
| C | [`03_prefab_in_mcp/`](03_prefab_in_mcp/) | `@mcp.tool(app=True)` — MCP tools that return real UIs instead of text. |
| D | [`04_talk_to_app/`](04_talk_to_app/) | The payoff: type an English sentence, get a working app in the browser. |

## One-time setup

```bash
pip install prefab-ui fastmcp google-genai python-dotenv
```

Prefab needs Python 3.10+. For lessons C and D you also need `GEMINI_API_KEY` in a `.env` file (same key you used for `AgenticMCPUse.py`).

## How to work through each lesson

1. Read the lesson's `README.md` end to end.
2. Open the lesson's code file and read it top to bottom.
3. Run it with the command in the README.
4. Do the "try these" exercises — they are the only way the ideas stick.
5. Answer the "ready check" questions before moving on.
