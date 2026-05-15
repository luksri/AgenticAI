import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv
import httpx
from fastmcp import FastMCP

from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge, Button, Card, CardContent, CardHeader, CardTitle,
    Checkbox, Column, H1, H2, H3, Muted, Progress, Ring, Row,
    Tab, Tabs, Text, Input, Calendar
)
from prefab_ui.components.charts import (
    BarChart, ChartSeries, LineChart, PieChart, Sparkline, RadarChart
)
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.rx import Rx

import db

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    # Try parent directory if not found in current
    load_dotenv(HERE.parent / ".env")
    api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("Warning: GEMINI_API_KEY not found in .env files.")

MODEL = "gemma4"
OLLAMA_URL = "http://localhost:11434/api/generate"

mcp = FastMCP("InteractiveTalkToApp")

# ---------------------------------------------------------------------------
# Renderer logic - now returning Components instead of strings
# ---------------------------------------------------------------------------

def render_widget(w: dict, ctx: dict):
    kind = w.get("kind", "")
    ctx["uid"] = ctx.get("uid", 0) + 1
    uid = ctx["uid"]

    if kind == "stat":
        label = w.get("label", "")
        value = str(w.get("value", ""))
        sub = w.get("sub", "")
        with Column(gap=1):
            Muted(label)
            H1(value)
            if sub:
                Muted(sub)
        return

    if kind == "badges":
        items = w.get("items", [])
        with Row(gap=2):
            for it in items:
                lbl = it.get("label", "") if isinstance(it, dict) else str(it)
                var = it.get("variant", "default") if isinstance(it, dict) else "default"
                Badge(lbl, variant=var)
        return

    if kind == "checklist":
        items = w.get("items", [])
        title = w.get("title")
        if title:
            H3(title)
        with Column(gap=2):
            for i, it in enumerate(items):
                label = it.get("label", f"Item {i+1}") if isinstance(it, dict) else str(it)
                checked = it.get("checked", False) if isinstance(it, dict) else False
                with Row(gap=3):
                    Checkbox(
                        name=f"cb_{uid}_{i}", 
                        value=checked,
                        on_change=CallTool("toggle_checklist_item", arguments={"uid": uid, "idx": i})
                    )
                    Text(label)
        return

    if kind == "progress_list":
        items = w.get("items", [])
        title = w.get("title")
        if title:
            H3(title)
        with Column(gap=3):
            for it in items:
                if not isinstance(it, dict): continue
                label = it.get("label", "")
                val = it.get("value", 0)
                with Column(gap=1):
                    Text(label)
                    Progress(value=val)
        return

    if kind == "ring":
        label = w.get("label", "")
        value = w.get("value", 0)
        suffix = w.get("suffix", "%")
        display = f"{value}{suffix}" if suffix else f"{value}"
        with Column(gap=2):
            if label: H3(label)
            Ring(value=value, label=display)
        return

    if kind == "pie":
        title = w.get("title", "")
        data = w.get("data", [])
        name_key = w.get("name_key", "name")
        value_key = w.get("value_key", "value")
        with Column(gap=2):
            if title: H3(title)
            PieChart(data=data, data_key=value_key, name_key=name_key, show_legend=True)
        return

    if kind == "bar":
        title = w.get("title", "")
        data = w.get("data", [])
        x_key = w.get("x_key", "x")
        y_keys = w.get("y_keys", ["y"])
        if isinstance(y_keys, str): y_keys = [y_keys]
        series = [ChartSeries(data_key=yk, label=yk) for yk in y_keys]
        with Column(gap=2):
            if title: H3(title)
            BarChart(data=data, series=series, x_axis=x_key, show_legend=len(y_keys) > 1)
        return

    if kind == "line":
        title = w.get("title", "")
        data = w.get("data", [])
        x_key = w.get("x_key", "x")
        y_keys = w.get("y_keys", ["y"])
        if isinstance(y_keys, str): y_keys = [y_keys]
        series = [ChartSeries(data_key=yk, label=yk) for yk in y_keys]
        with Column(gap=2):
            if title: H3(title)
            LineChart(data=data, series=series, x_axis=x_key, show_legend=len(y_keys) > 1)
        return

    if kind == "sparkline":
        values = w.get("values", [])
        title = w.get("title", "")
        with Column(gap=2):
            if title: H3(title)
            Sparkline(data=values)
        return

    if kind == "table":
        title = w.get("title", "")
        columns = w.get("columns", [])
        rows = w.get("rows", [])
        with Column(gap=2):
            if title: H3(title)
            with Row(gap=3):
                for col in columns: Text(str(col))
            for row in rows:
                with Row(gap=3):
                    cells = row if isinstance(row, list) else [row.get(c, "") for c in columns]
                    for cell in cells: Text(str(cell))
        return

    if kind == "text":
        heading = w.get("heading", "")
        body = w.get("body", "")
        level = str(w.get("level", "h3")).lower()
        with Column(gap=1):
            if heading:
                if level == "h1": H1(heading)
                elif level == "h2": H2(heading)
                else: H3(heading)
            if body: Muted(body)
        return

    if kind == "calendar_heatmap":
        title = w.get("title", "")
        data = w.get("data", [])
        date_key = w.get("date_key", "date")
        value_key = w.get("value_key", "value")
        with Column(gap=2):
            if title: H3(title)
            Calendar(data=data, date_key=date_key, value_key=value_key)
        return

    if kind == "radar":
        title = w.get("title", "")
        data = w.get("data", [])
        axis_key = w.get("axis_key", "axis")
        y_keys = w.get("y_keys", ["value"])
        if isinstance(y_keys, str): y_keys = [y_keys]
        series = [ChartSeries(data_key=yk, label=yk) for yk in y_keys]
        with Column(gap=2):
            if title: H3(title)
            RadarChart(data=data, series=series, axis_key=axis_key, show_legend=len(y_keys) > 1)
        return

    Muted(f"Unknown widget kind: {kind!r}")

# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool(app=True)
def dashboard() -> PrefabApp:
    """Show the interactive persistent dashboard."""
    spec = db.get_spec()
    params = spec.get("params", {})
    title = params.get("title", "Dashboard")
    tabs = params.get("tabs", [])
    
    ctx = {"uid": 0}
    user_prompt = Rx("user_prompt")
    is_loading = Rx("is_loading")

    with PrefabApp(state={"user_prompt": "", "is_loading": False}, css_class="max-w-5xl mx-auto p-6") as app:
        with Card():
            with CardHeader():
                with Row(justify="between", align="center"):
                    CardTitle(title)
                    with Row(gap=2, align="center"):
                        Input(name="user_prompt", placeholder="Describe a change...", css_class="w-64")
                        Button(
                            "Update App", 
                            on_click=[
                                SetState("is_loading", True),
                                CallTool("update_dashboard", arguments={"prompt": "{{ user_prompt }}"})
                            ],
                            variant="default"
                        )
            
            with CardContent():
                if is_loading:
                    with Column(align="center", justify="center", css_class="py-12"):
                        Muted("Gemini is thinking...")
                else:
                    if not tabs:
                        Muted("No tabs defined.")
                    else:
                        first_tab_value = re.sub(r"[^a-z0-9]+", "_", tabs[0].get("name", "tab").lower())
                        with Tabs(value=first_tab_value):
                            for i, tab in enumerate(tabs):
                                name = tab.get("name", f"Tab {i+1}")
                                val = re.sub(r"[^a-z0-9]+", "_", name.lower())
                                with Tab(name, value=val):
                                    with Column(gap=5):
                                        widgets = tab.get("widgets", [])
                                        for w in widgets:
                                            render_widget(w, ctx)
    return app

PLANNER_PROMPT = """You design small interactive dashboards. Given the user's sentence
and the CURRENT dashboard spec (if any), respond with the spec for the
dashboard that should be shown next.

You have ONE template: `dashboard`. Its spec is:
  {{
    "template": "dashboard",
    "params": {{
      "title": "<app title>",
      "tabs": [
        {{ "name": "<tab label>", "widgets": [ ... ] }},
        ...
      ]
    }}
  }}

Each tab's widgets is an ORDERED list. Each widget is one of:
  {{"kind": "stat",           "label": "...", "value": "...", "sub": "..."}}
  {{"kind": "badges",         "items": [{{"label": "...", "variant": "default|success|warning|destructive"}}, ...]}}
  {{"kind": "checklist",      "title": "...", "items": [{{"label": "...", "checked": bool}}, ...]}}
  {{"kind": "progress_list",  "title": "...", "items": [{{"label": "...", "value": 0..100}}, ...]}}
  {{"kind": "ring",           "label": "...", "value": 0..100, "suffix": "%"}}
  {{"kind": "pie",            "title": "...", "data": [{{"name": "...", "value": <number>}}, ...], "name_key": "name", "value_key": "value"}}
  {{"kind": "bar",            "title": "...", "data": [{{"x": "...", "y": <number>}}, ...], "x_key": "x", "y_keys": ["y"]}}
  {{"kind": "line",           "title": "...", "data": [...], "x_key": "x", "y_keys": ["y"] }}
  {{"kind": "sparkline",      "title": "...", "values": [<number>, ...]}}
  {{"kind": "table",          "title": "...", "columns": ["Col A", ...], "rows": [["v1","v2",...], ...]}}
  {{"kind": "text",           "heading": "...", "body": "...", "level": "h1|h2|h3"}}
  {{"kind": "calendar_heatmap", "title": "...", "data": [{{"date": "YYYY-MM-DD", "value": <number>}}, ...], "date_key": "date", "value_key": "value"}}
  {{"kind": "radar", "title": "...", "data": [{{"axis": "...", "value": <number>}}, ...], "axis_key": "axis", "y_keys": ["value"]}}

Guidelines:
- Mix widget kinds — a good tab has a headline stat, some visual (chart/ring), and a list/table.
- If the user is MODIFYING the current dashboard, preserve unaffected tabs and widgets.
- Respond with EXACTLY ONE JSON object (no prose, no code fences):
  {{"template": "dashboard", "params": {{...}}}}

Current spec: {current_spec}
User request: {user_request}
"""

@mcp.tool(app=True)
def update_dashboard(prompt: str) -> PrefabApp:
    """Call Gemini to update the dashboard spec and return the new UI."""
    current_spec = db.get_spec()
    full_prompt = PLANNER_PROMPT.format(
        user_request=prompt,
        current_spec=json.dumps(current_spec)
    )
    
    # Call Ollama
    payload = {
        "model": MODEL,
        "prompt": full_prompt,
        "stream": False
    }
    try:
        r = httpx.post(OLLAMA_URL, json=payload, timeout=180)
        raw = r.json().get("response", "").strip()
    except Exception as e:
        print(f"Ollama Error: {e}")
        return dashboard()

    if raw.startswith("```"):
        # Basic JSON extractor
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        else:
            raw = raw.split("```")[1].split("```")[0].strip()
    
    try:
        new_spec = json.loads(raw)
        db.save_spec(new_spec)
    except Exception as e:
        # Fallback if LLM fails
        return dashboard()

    return dashboard()

@mcp.tool(app=True)
def toggle_checklist_item(uid: int, idx: int) -> PrefabApp:
    """Toggle a checkbox in the spec and persist the change."""
    spec = db.get_spec()
    tabs = spec.get("params", {}).get("tabs", [])
    
    current_uid = 0
    found = False
    for tab in tabs:
        for widget in tab.get("widgets", []):
            if widget.get("kind") == "checklist":
                current_uid += 1
                if current_uid == uid:
                    items = widget.get("items", [])
                    if 0 <= idx < len(items):
                        item = items[idx]
                        if isinstance(item, dict):
                            item["checked"] = not item.get("checked", False)
                        else:
                            items[idx] = {"label": str(item), "checked": True}
                        found = True
                        break
        if found: break
    
    if found:
        db.save_spec(spec)
    
    return dashboard()

@mcp.tool(app=True)
def render_widgets(widgets: list, title: str = "Agent Generated UI") -> PrefabApp:
    """
    Render a specific list of widgets directly into a dashboard.
    This allows an external agent to have full control over the UI components.
    """
    # Create a simple single-tab spec from the provided widgets
    spec = {
        "params": {"title": title},
        "tabs": [{"name": "Main", "widgets": widgets}]
    }
    
    # Save to DB so it persists
    db.save_spec(spec)
    
    # Return the rendered app
    return dashboard()

if __name__ == "__main__":
    db.init_db()
    mcp.run()
