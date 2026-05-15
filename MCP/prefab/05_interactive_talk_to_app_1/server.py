"""
Lesson D — Talk-to-App (v5: generic dashboard).

One template. Any domain. The LLM composes a dashboard from a catalog of
widgets (stat, badges, checklist, progress_list, ring, pie, bar, line,
sparkline, table, text). Every call produces a dashboard spec — the LLM
picks the tabs, picks the widgets, fills the data.

Run:
    python prompt_to_app.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
import httpx

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

from dotenv import load_dotenv
from google import genai

load_dotenv()

# Use local model by default
MODEL = "gemma4"
OLLAMA_URL = "http://localhost:11434/api/generate"

mcp = FastMCP("PrefabTeachingMCPserver")

# ---------------------------------------------------------------------------
# Widget renderers. Each returns a list of Python source lines with ZERO
# leading indentation. The dashboard template indents them into place.
# ---------------------------------------------------------------------------

def _slug(s: str, default: str = "k") -> str:
    out = re.sub(r"[^a-zA-Z0-9_]+", "_", str(s)).strip("_").lower()
    return out or default


def _safe(name: str, idx: int, default: str = "item") -> str:
    return _slug(name, default) or f"{default}_{idx}"


def widget_lines(w: dict, ctx: dict) -> list[str]:
    kind = w.get("kind", "")
    ctx["uid"] = ctx.get("uid", 0) + 1
    uid = ctx["uid"]

    if kind == "stat":
        label = w.get("label", "")
        value = str(w.get("value", ""))
        sub = w.get("sub", "")
        out = [
            'with Column(gap=1):',
            f'    Muted({label!r})',
            f'    H1({value!r})',
        ]
        if sub:
            out.append(f'    Muted({sub!r})')
        return out

    if kind == "badges":
        items = w.get("items", [])
        out = ['with Row(gap=2):']
        for it in items:
            lbl = it.get("label", "") if isinstance(it, dict) else str(it)
            var = it.get("variant", "default") if isinstance(it, dict) else "default"
            out.append(f'    Badge({lbl!r}, variant={var!r})')
        return out or ['Muted("(no badges)")']

    if kind == "checklist":
        items = w.get("items", [])
        title = w.get("title")
        out: list[str] = []
        if title:
            out += [f'H3({title!r})']
        out += ['with Column(gap=2):']
        for i, it in enumerate(items):
            label = it.get("label", f"Item {i+1}") if isinstance(it, dict) else str(it)
            out += [
                '    with Row(gap=3):',
                f'        Checkbox(name="cb_{uid}_{i}")',
                f'        Text({label!r})',
            ]
        return out

    if kind == "progress_list":
        items = w.get("items", [])
        title = w.get("title")
        out: list[str] = []
        if title:
            out += [f'H3({title!r})']
        out += ['with Column(gap=3):']
        for it in items:
            if not isinstance(it, dict):
                continue
            label = it.get("label", "")
            val = it.get("value", 0)
            try:
                val = max(0, min(100, int(val)))
            except Exception:
                val = 0
            out += [
                '    with Column(gap=1):',
                f'        Text({label!r})',
                f'        Progress(value={val})',
            ]
        return out

    if kind == "ring":
        label = w.get("label", "")
        value = w.get("value", 0)
        try:
            value = max(0, min(100, int(value)))
        except Exception:
            value = 0
        suffix = w.get("suffix", "%")
        display = f"{value}{suffix}" if suffix else f"{value}"
        out = ['with Column(gap=2):']
        if label:
            out.append(f'    H3({label!r})')
        out.append(f'    Ring(value={value}, label={display!r})')
        return out

    if kind == "pie":
        title = w.get("title", "")
        data = w.get("data", [])
        name_key = w.get("name_key", "name")
        value_key = w.get("value_key", "value")
        # Ensure data is list of dicts with those keys.
        clean = []
        for row in data:
            if isinstance(row, dict) and name_key in row and value_key in row:
                clean.append({name_key: row[name_key], value_key: row[value_key]})
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out.append(
            f'    PieChart(data={clean!r}, data_key={value_key!r}, '
            f'name_key={name_key!r}, show_legend=True)'
        )
        return out

    if kind == "bar":
        title = w.get("title", "")
        data = w.get("data", [])
        x_key = w.get("x_key", "x")
        y_keys = w.get("y_keys", ["y"])
        if isinstance(y_keys, str):
            y_keys = [y_keys]
        series_lines = ", ".join(f'ChartSeries(data_key={yk!r}, label={yk!r})' for yk in y_keys)
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out += [
            f'    BarChart(data={data!r},',
            f'             series=[{series_lines}],',
            f'             x_axis={x_key!r}, show_legend={len(y_keys) > 1})',
        ]
        return out

    if kind == "line":
        title = w.get("title", "")
        data = w.get("data", [])
        x_key = w.get("x_key", "x")
        y_keys = w.get("y_keys", ["y"])
        if isinstance(y_keys, str):
            y_keys = [y_keys]
        series_lines = ", ".join(f'ChartSeries(data_key={yk!r}, label={yk!r})' for yk in y_keys)
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out += [
            f'    LineChart(data={data!r},',
            f'              series=[{series_lines}],',
            f'              x_axis={x_key!r}, show_legend={len(y_keys) > 1})',
        ]
        return out

    if kind == "sparkline":
        values = w.get("values", [])
        title = w.get("title", "")
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out.append(f'    Sparkline(data={values!r})')
        return out

    if kind == "table":
        title = w.get("title", "")
        columns = w.get("columns", [])
        rows = w.get("rows", [])
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        # Header row
        out.append('    with Row(gap=3):')
        for col in columns:
            out.append(f'        Text({str(col)!r})')
        # Data rows
        for row in rows:
            out.append('    with Row(gap=3):')
            cells = row if isinstance(row, list) else [row.get(c, "") for c in columns]
            for cell in cells:
                out.append(f'        Text({str(cell)!r})')
        return out

    if kind == "text":
        heading = w.get("heading", "")
        body = w.get("body", "")
        level = str(w.get("level", "h3")).lower()
        out = ['with Column(gap=1):']
        if heading:
            if level == "h1":
                out.append(f'    H1({heading!r})')
            elif level == "h2":
                out.append(f'    H2({heading!r})')
            else:
                out.append(f'    H3({heading!r})')
        if body:
            out.append(f'    Muted({body!r})')
        return out

    if kind == "calendar_heatmap":
        title = w.get("title", "")
        data = w.get("data", [])
        date_key = w.get("date_key", "date")
        value_key = w.get("value_key", "value")
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out.append(
            f'    Calendar(data={data!r}, date_key={date_key!r}, '
            f'value_key={value_key!r})'
        )
        return out

    if kind == "radar":
        title = w.get("title", "")
        data = w.get("data", [])
        axis_key = w.get("axis_key", "axis")
        y_keys = w.get("y_keys", ["value"])
        if isinstance(y_keys, str):
            y_keys = [y_keys]
        series_lines = ", ".join(f'ChartSeries(data_key={yk!r}, label={yk!r})' for yk in y_keys)
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out += [
            f'    RadarChart(data={data!r},',
            f'               series=[{series_lines}],',
            f'               axis_key={axis_key!r}, show_legend={len(y_keys) > 1})',
        ]
        return out

    return [f'Muted({f"Unknown widget kind: {kind!r}"!r})']


# ---------------------------------------------------------------------------
# The one template.
# ---------------------------------------------------------------------------

def dashboard(title: str, tabs: list[dict]) -> str:
    # Normalise tabs.
    if not tabs:
        tabs = [{"name": "Main", "widgets": [{"kind": "text", "heading": "Empty dashboard"}]}]

    ctx: dict = {"uid": 0}
    TAB_INDENT = " " * 24          # body of `with Column(gap=5):` at 20 spaces
    WIDGET_SEP = "\n\n" + TAB_INDENT[:-4]  # tiny gap comment not required

    built_tabs: list[tuple[str, str, str]] = []  # (name, value, indented_body)
    for i, tab in enumerate(tabs):
        name = str(tab.get("name") or f"Tab {i+1}")
        value = _slug(tab.get("value") or name, f"tab_{i+1}")
        widgets = tab.get("widgets") or []
        body_lines: list[str] = []
        if not widgets:
            body_lines = [TAB_INDENT + 'Muted("(empty tab)")']
        else:
            for w in widgets:
                for line in widget_lines(w, ctx):
                    body_lines.append((TAB_INDENT + line) if line else "")
        built_tabs.append((name, value, "\n".join(body_lines)))

    first_value = built_tabs[0][1]

    parts = [
        "from prefab_ui.app import PrefabApp",
        "from prefab_ui.components import (",
        "    Badge, Button, Card, CardContent, CardHeader, CardTitle,",
        "    Checkbox, Column, H1, H2, H3, Muted, Progress, Ring, Row,",
        "    Tab, Tabs, Text, Calendar",
        ")",
        "from prefab_ui.components.charts import (",
        "    BarChart, ChartSeries, LineChart, PieChart, Sparkline, RadarChart,",
        ")",
        "",
        "@mcp.tool(app=True)",
        "def dummy_app() -> PrefabApp:",
        '    with PrefabApp(css_class="max-w-5xl mx-auto p-6") as app:',
        "        with Card():",
        "            with CardHeader():",
        f"                CardTitle({title!r})",
        "        with CardContent():",
        f"            with Tabs(value={first_value!r}):",
    ]
    for name, value, body in built_tabs:
        parts.append(f'                with Tab({name!r}, value={value!r}):')
        parts.append("                    with Column(gap=5):")
        parts.append(body)
    parts.append("    return app")
    return "\n".join(parts) + "\n"


TEMPLATES = {"dashboard": dashboard}


# ---------------------------------------------------------------------------
# Planner — one template, full widget catalog, edit-aware.
# ---------------------------------------------------------------------------

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

  {{"kind": "stat",           "label": "<small label>", "value": "<big text>", "sub": "<optional caption>"}}
  {{"kind": "badges",         "items": [{{"label": "...", "variant": "default|success|warning|destructive"}}, ...]}}
  {{"kind": "checklist",      "title": "<optional>", "items": [{{"label": "..."}}, ...]}}
  {{"kind": "progress_list",  "title": "<optional>", "items": [{{"label": "...", "value": 0..100}}, ...]}}
  {{"kind": "ring",           "label": "<optional>", "value": 0..100, "suffix": "%"}}
  {{"kind": "pie",            "title": "<optional>", "data": [{{"name": "...", "value": <number>}}, ...]}}
  {{"kind": "bar",            "title": "<optional>", "data": [{{"x": "...", "y": <number>, ...}}, ...], "x_key": "x", "y_keys": ["y"]}}
  {{"kind": "line",           "title": "<optional>", "data": [...], "x_key": "x", "y_keys": ["y"] }}
  {{"kind": "sparkline",      "title": "<optional>", "values": [<number>, ...]}}
  {{"kind": "table",          "title": "<optional>", "columns": ["Col A", ...], "rows": [["v1","v2",...], ...]}}
  {{"kind": "text",           "heading": "<optional>", "body": "<optional>", "level": "h1|h2|h3"}}
  {{"kind": "calendar_heatmap", "title": "<optional>", "data": [{{"date": "YYYY-MM-DD", "value": <number>}}, ...], "date_key": "date", "value_key": "value"}}
  {{"kind": "radar", "title": "<optional>", "data": [{{"axis": "...", "value": <number>, ...}}, ...], "axis_key": "axis", "y_keys": ["value"]}}

Guidelines:
- Pick tab names that fit the domain (e.g. for a stock tracker: Portfolio, P&L, Watchlist).
- Mix widget kinds — a good tab has a headline stat, some visual (chart/ring), and a list/table.
- Invent realistic-looking sample data (5–8 items usually).
- If the user is MODIFYING the current dashboard, preserve unaffected tabs and widgets.
- For "add a pie chart on the X tab", append or insert a pie widget to that tab.

Respond with EXACTLY ONE JSON object (no prose, no code fences):
  {{"template": "dashboard", "params": {{...}}}}

User request: {user_request}
"""


# def plan(user_request: str, current_spec: dict | None) -> dict:
#     prompt = PLANNER_PROMPT.format(
#         user_request=user_request,
#         current_spec=json.dumps(current_spec) if current_spec else "null",
#     )
#     response = client.models.generate_content(model=MODEL, contents=prompt)
#     raw = (response.text or "").strip()
#     if raw.startswith("```"):
#         raw = raw.strip("`").split("\n", 1)[1].rsplit("\n", 1)[0]
#     return json.loads(raw)

def plan(user_request: str) -> dict:
    prompt = PLANNER_PROMPT.format(
        user_request=user_request
    )
    # Call Ollama
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "format": "json",
        "options": {
            "num_predict": 4096
        },
        "stream": False
    }
    try:
        r = httpx.post(OLLAMA_URL, json=payload, timeout=180)
        raw = r.json().get("response", "").strip()
    except Exception as e:
        print(f"Ollama Error: {e}")
        raise e

    print(f"DEBUG: Raw response from Ollama: {repr(raw)}")
    
    # More robust JSON extraction
    # Find the first { and the last }
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end+1]
        
        # Strip common hallucinated prose if still present
        if raw.startswith("```json"):
            raw = raw[7:].strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        raw = raw.strip("`").strip()
            
        return json.loads(raw)
    except Exception as e:
        print(f"JSON Parse Error: {e}")
        print(f"Attempted to parse: {raw}")
        raise e

@mcp.tool(app=True)
def write_app(user_request: str) -> PrefabApp:
    spec = plan(user_request)
    print(f"  plan: {json.dumps(spec)[:240]}"
            + ("..." if len(json.dumps(spec)) > 240 else ""))
    name = spec.get("template", "dashboard")
    params = spec.get("params", {})
    if name not in TEMPLATES:
        raise ValueError(f"Unknown template {name!r}.")
    source = TEMPLATES[name](**params)
    
    # Syntax check
    compile(source, "<generated_app>", "exec")
    
    # Execute the generated code and get the app
    exec_globals = globals().copy()
    exec(source, exec_globals)
    app = exec_globals["dummy_app"]()
    
    # Return the app (for Claude), the raw spec (backward compatibility), 
    # and the full Python source (for the new simple frontend)
    # return [
    #     app,
    #     f"DASHBOARD_DATA:{json.dumps(spec)}",
    #     f"PREFAB_SOURCE:{source}"
    # ]
    return app




if __name__ == "__main__":
    mcp.run()
    # write_app("Create a dashboard with 3 tabs.")
