# Lesson D — Talk-to-App

You have reached the moment this whole track was built for. Close your laptop for a second and read this paragraph carefully.

You are about to run a program that does this: you type one English sentence describing an app you want. The program calls an LLM. The LLM returns a spec — a set of tabs and, inside each tab, a list of widgets (charts, stats, tables, lists). Your Python code turns that spec into a Prefab file. The browser reconnects. A real, clickable, interactive, multi-tab app is sitting there — the app you described, built in the seconds between hitting enter and Prefab rendering. Then you change your mind and type *"add a watchlist tab with 5 stocks"*, and the *same* app morphs.

That is the demo. Let's build it.

## The architecture, in one picture

```
  you type              LLM returns a            we render the spec         prefab serve
  "stock tracker    ──► dashboard spec      ───► into a Prefab file    ───► in a subprocess   ───► browser shows
   with P&L tab"        {tabs, widgets, data}    on disk                    (we restart it)          a live multi-tab app
```

Four pieces, and you have met every single one of them already in this track:

1. The **LLM call** is the same pattern from `AgenticMCPUse.py`.
2. The **spec protocol** is the same "respond with a structured directive" idea we used for FUNCTION_CALL — dressed up in JSON because a dashboard spec has more structure.
3. The **Prefab file** is exactly the `with PrefabApp(): ...` DSL from Lessons A and B.
4. The **`prefab serve`** command is what you ran in Lessons A and B.

Nothing new. Just stitched together.

## The one big idea: the LLM does not write UI code

Read that again. This is the design decision that makes everything else work.

The LLM has a fixed **catalog of widgets** to pick from, and a fixed **shape of spec** to fill out. It never emits Prefab component calls directly. It never imports anything. It never touches Python syntax. It just chooses widgets from a menu and fills in their data. That is a task LLMs are reliable at — closer to *"fill this form"* than *"write this program"*.

You (the teacher) control the menu. Expressiveness grows with the catalog, not with LLM cleverness. Adding a new capability = one new widget renderer in `prompt_to_app.py`.

## The pieces in [prompt_to_app.py](prompt_to_app.py)

- **One template: `dashboard(title, tabs)`.** A dashboard is a titled card with a set of tabs. Each tab holds an ordered list of widgets. That's it — no domain assumptions.

- **A widget catalog.** Each widget knows how to render itself from a small dict of parameters. The current catalog:

  | Widget | What it renders |
  |---|---|
  | `stat` | A big number with a small label and an optional caption |
  | `badges` | A horizontal row of labeled badges (with variants: default / success / warning / destructive) |
  | `checklist` | A list of items with checkboxes |
  | `progress_list` | A list of labeled progress bars |
  | `ring` | A big completion dial (value + label) |
  | `pie` | `PieChart` from a list of `{name, value}` rows |
  | `bar` | `BarChart` from a list of rows plus an x-axis key and y-axis series |
  | `line` | `LineChart` with the same shape as `bar` |
  | `sparkline` | A mini trend line of raw numbers |
  | `table` | A columns-and-rows data table |
  | `text` | A heading (`h1`/`h2`/`h3`) with optional body text |

  Every widget is one `if kind == "...":` block inside `widget_lines()`. Read one, you've read them all.

- **A planner prompt** that is given the user's sentence and the **current spec** (if any). If the user is starting fresh, the LLM composes a new dashboard. If they are modifying (*"add a watchlist tab"*, *"swap the pie chart for a bar chart"*), the LLM edits the existing spec and returns the new one.

- **A writer** that takes the spec, renders it through the dashboard template (which dispatches each widget through the catalog), syntax-checks the resulting Python, and writes it to `generated_app.py`.

- **A Prefab subprocess** (`PrefabServer` class). Every time we regenerate the file, we **restart the subprocess**. Prefab's `--reload` flag *should* refresh the browser automatically, but in practice the auto-refresh was unreliable — so we do a hard restart. The visible cost is a brief "reconnecting..." state in the tab.

- **Crash detection + rollback.** If the generated file makes Prefab choke, the REPL prints the log tail and reverts to the last working app, so the browser is never stuck on a dead page.

## Run it

```bash
pip install prefab-ui google-genai python-dotenv
```

Make sure `GEMINI_API_KEY` is in your `.env` (same one you used for `AgenticMCPUse.py`). Then:

```bash
python prompt_to_app.py
```

The script starts `prefab serve generated_app.py` in the background (its logs go to `prefab_server.log`), tells you to open `http://127.0.0.1:5175` in a browser tab, and prompts you with `What do you want to build (or change)?`.

Try these, one at a time. Hit enter after each. **Keep the browser tab visible**.

1. *"A stock tracker with splits by industry, returns, and concerns. Portfolio tab and a P&L tab."*
2. *"Add a watchlist tab with a table of 5 stocks to watch."* (existing dashboard gets a new tab)
3. *"On the Portfolio tab, add a sparkline of 30-day portfolio value."* (widget appended to an existing tab)
4. *"Swap the industry pie chart for a bar chart."* (widget replaced in place)
5. *"Actually give me a CRM dashboard instead — tabs for Leads, Pipeline, Customers."* (full rebuild, different domain)
6. *"A habit tracker for water, steps, reading, meditation, and yoga."* (different domain again)
7. *"A pomodoro timer for 15 minutes."* (tiny one-tab app)

Prompts 2–4 are *edits* — the planner sees the previous spec and returns a modified one. Prompts 5–7 switch domain entirely. All of it happens with no code written by you.

## Why this is the future, said plainly

Look at what just happened:

- **The UI is Python.** Every component is a function call with typed arguments.
- **The Python is LLM-writable.** Because the LLM only fills in a small structured spec, it does not need to generate HTML or know about selectors. It just picks widgets from a menu and fills in data. That is a task LLMs are reliable at.
- **The feedback is instant.** Generation → rendering takes a couple of seconds.
- **The user's language is the IDE.** The loop is: *think of an app, describe it, use it, tell it to change, use it some more.*

For ten years, building "a little internal tool" cost an afternoon and a frontend dev. You just did it in a sentence, and the cost was one LLM call. That compounds. Every team, every person, every passing idea that used to not-be-worth-building is now worth building. That is what "the future" looks like in practice: a massive widening of the set of things cheap enough to do.

## What this demo is NOT, and what comes next

Be honest with yourself about two things this version does not do yet:

1. **No persistence.** Tick a box, restart the script, the tick is gone. Each run starts from the spec's seed data. Client-side reactive state lives in the browser tab, nowhere else.
2. **Prompting still happens in the terminal.** The browser is a viewer; you cannot type into the app itself to change it.

Both problems have the same root cause — Prefab's client-side actions do not, by themselves, call back to Python. To add either feature, you need a server-side callback. The cleanest route is the one you already saw in Lesson C:

- Wrap this whole generator as an **MCP app** (`@mcp.tool(app=True)`).
- Inside the generated Prefab tree, put an `Input` and a Button whose `on_click` is `CallTool("plan_app", arguments={"prompt": "{{ prompt }}"})`.
- The tool receives the prompt, calls Gemini, writes a new spec to SQLite, and returns a new `PrefabApp`.
- Do the same for "tick a checkbox": a Checkbox whose `on_success` calls an MCP tool that writes the change to SQLite.

That is the version where the user types in the browser, data survives refresh, and nothing is ever lost. It is the natural project that follows this lesson.

## Things to try

1. **Add a new widget kind.** Pick one — `calendar_heatmap`, `avatar_list`, `radar_chart`. You will touch exactly two places: add an `if kind == "...":` block inside `widget_lines()`, and add a line to the planner prompt's widget menu so the LLM knows to use it.
2. **Add a second template** (e.g. a `wizard` template with "next/back" navigation). Not every app is a dashboard; a wizard has different ergonomics. Add it to `TEMPLATES` and mention it in the planner prompt.
3. **Teach it your data.** Replace the LLM's invented sample data with real data from an SQLite DB, a CSV, or an API — by writing a fetcher and passing the result into the planner prompt as context.

## Ready check

1. Where in the code does a widget in the JSON spec turn into actual Prefab Python source?
2. If the generated file breaks Prefab (bad import, wrong arg), what does the script do to keep the browser usable?
3. If you wanted the agent to be able to draw a **radar chart**, which two places in `prompt_to_app.py` would you touch, and in what order?

If those three are easy, you have understood the whole track. Go build something.
