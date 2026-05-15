# agent.py — Gemini ReAct agent with RAG tools (LangGraph-based, LangChain 1.x)

import os
from typing import Optional
from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent
from langchain_tavily import TavilySearch
import rag
import json
from google import genai
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import mcp_config


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


# ── LLM ────────────────────────────────────────────────────────────────────
def _get_llm():
    return ChatOllama(
        model="gemma4",
        temperature=0.3,
    )


# ── Tools ───────────────────────────────────────────────────────────────────
@tool
def query_rag(question: str, topic: Optional[str] = None) -> str:
    """
    Search the knowledge base for information relevant to the question.
    Optionally filter by topic. Returns the most relevant text chunks with their sources.
    Use this tool whenever the user asks a question that may be answered from collected knowledge.
    """
    results = rag.query(topic=topic, query_text=question, k=5)
    if not results:
        return "No relevant information found in the knowledge base."
    formatted = []
    for i, r in enumerate(results, 1):
        formatted.append(
            f"[{i}] Source: {r['source']}\nTopic: {r['topic']}\n{r['content']}"
        )
    return "\n\n---\n\n".join(formatted)


@tool
def list_topics() -> str:
    """
    List all available topics in the knowledge base with their document counts.
    Use this when the user asks what topics are available or to understand the scope.
    """
    topics = rag.list_topics()
    if not topics:
        return "No topics found. The knowledge base is empty."
    lines = [f"• {t['name']} — {t['doc_count']} docs from {t['source_count']} sources" for t in topics]
    return "Available topics:\n" + "\n".join(lines)


@tool
def get_topic_stats(topic: str) -> str:
    """
    Get detailed statistics for a specific topic: doc count, sources, last update time.
    """
    topics = rag.list_topics()
    match = next((t for t in topics if t["name"].lower() == topic.lower()), None)
    if not match:
        return f"Topic '{topic}' not found."
    return (
        f"Topic: {match['name']}\n"
        f"Documents: {match['doc_count']}\n"
        f"Unique sources: {match['source_count']}\n"
        f"Last updated: {match['last_updated']}"
    )


@tool
def internet_search(query: str) -> str:
    """
    Search the public internet using Tavily.
    Use this tool if the user's question cannot be answered from the collected knowledge base,
    or if the user specifically asks to search the web/internet.
    """
    tavily = TavilySearch(max_results=3)
    return str(tavily.invoke({"query": query}))


@tool
def create_chart(chart_type: str, data: list[dict], title: str, x: str, y: str) -> str:
    """
    Generate a visualization (graph/chart) for the user.
    chart_type: One of 'bar', 'line', 'area', 'pie', 'scatter'.
    data: A list of dictionaries containing the data points (e.g. [{"name": "A", "value": 10}, ...]).
    title: The title of the chart.
    x: The key in the data dictionaries to use for the X-axis (labels).
    y: The key in the data dictionaries to use for the Y-axis (values).
    Use this tool whenever the user asks for a graph, visualization, or to see data plotted.
    """
    chart_info = {
        "type": "chart",
        "chart_type": chart_type,
        "data": data,
        "title": title,
        "x": x,
        "y": y
    }
    return f"VISUAL_DATA:{json.dumps(chart_info)}"


@tool
def create_dashboard(prompt: str, topic: Optional[str] = None) -> str:
    """
    Generate a full interactive dashboard with multiple widgets (stats, charts, checklists, etc.).
    prompt: A description of what the dashboard should show (e.g. "A summary of my research on renewable energy").
    topic: The specific topic this dashboard relates to.
    Use this tool when the user asks for a 'dashboard', 'overview', 'summary report', or a complex visual layout.
    """
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    
    PLANNER_PROMPT = """You design interactive dashboards based on RAG knowledge.
Respond with EXACTLY ONE JSON object (no prose, no code fences):
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

Available widgets:
- {{"kind": "stat", "label": "...", "value": "...", "sub": "..."}}
- {{"kind": "badges", "items": [{{"label": "...", "variant": "default|success|warning|destructive"}}, ...]}}
- {{"kind": "checklist", "title": "...", "items": [{{"label": "...", "checked": bool}}, ...]}}
- {{"kind": "progress_list", "title": "...", "items": [{{"label": "...", "value": 0..100}}, ...]}}
- {{"kind": "ring", "label": "...", "value": 0..100, "suffix": "%"}}
- {{"kind": "pie", "title": "...", "data": [...], "name_key": "name", "value_key": "value"}}
- {{"kind": "bar", "title": "...", "data": [...], "x_key": "x", "y_keys": ["y"]}}
- {{"kind": "line", "title": "...", "data": [...], "x_key": "x", "y_keys": ["y"]}}
- {{"kind": "radar", "title": "...", "data": [...], "axis_key": "axis", "y_keys": ["value"]}}
- {{"kind": "text", "heading": "...", "body": "...", "level": "h1|h2|h3"}}

User request: {prompt}
Topic: {topic}
"""
    response = client.models.generate_content(
        model="gemini-2.0-flash", 
        contents=PLANNER_PROMPT.format(prompt=prompt, topic=topic)
    )
    raw = (response.text or "").strip()
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    
    return f"DASHBOARD_DATA:{raw}"


@tool
def save_dashboard(spec: dict, title: str = "New Dashboard") -> str:
    """
    Saves a dashboard specification to a local file for the frontend to render.
    Use this whenever you want to display a dashboard, overview, or report to the user.
    'spec' must be the JSON object containing 'template' and 'params'.
    """
    data = {"spec": spec, "title": title}
    with open("latest_dashboard.json", "w") as f:
        json.dump(data, f)
    
    # Also save to DB for persistence
    import dashboard_db
    dashboard_db.save_dashboard(spec=spec, title=title)
    
    return f"DASHBOARD_DATA:{json.dumps(spec)}"


def _call_mcp_dashboard_sync(prompt: str, widgets: list = None):
    """Synchronous wrapper for MCP client call using mcp_config."""
    async def run():
        config = mcp_config.DASHBOARD_MCP_SERVER
        if not config.get("enabled"):
            return "Error: Dashboard MCP server is disabled in mcp_config.py"

        server_params = StdioServerParameters(
            command=config["command"],
            args=config["args"],
            env=os.environ.copy()
        )
        
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    # Always use write_app as per user requirement
                    result = await session.call_tool("write_app", arguments={"user_request": prompt})
                    
                    # Search for the dashboard data or source code in the tool output
                    for item in getattr(result, 'content', []):
                        if hasattr(item, 'text'):
                            if "PREFAB_SOURCE:" in item.text:
                                return item.text
                            if "DASHBOARD_DATA:" in item.text:
                                return item.text
                            if "{" in item.text and "template" in item.text:
                                return item.text
                            
                    if result.content and len(result.content) > 0:
                        return result.content[0].text
                    return "Error: No content from MCP server"
        except Exception as e:
            return f"Error connecting to MCP server: {str(e)}"

    return asyncio.run(run())


@tool
def generate_mcp_dashboard(prompt: str, widgets: list = None) -> str:
    """
    Delegates complex dashboard/UI rendering to the specialized 'InteractiveTalkToApp' MCP server.
    - If you provide 'widgets' (a list of dicts), the server will render those specific components instantly.
    - If you only provide a 'prompt', the server's internal planner will design the layout for you.
    Use this for any request for a 'plot', 'interactive app', 'visual summary', or 'advanced dashboard'.
    """
    result = _call_mcp_dashboard_sync(prompt, widgets=widgets)
    
    # The MCP server saves to its own spec.db and potentially returns JSON.
    # We'll try to extract DASHBOARD_DATA if it looks like JSON.
    if "{" in result and "template" in result:
        try:
            # Clean up the string if it has PrefabApp(...) wrapper
            if "PrefabApp(" in result:
                # Simple extraction of what's inside PrefabApp(...)
                # But actually, the server.py writes to latest_dashboard.json too if we modified it?
                # No, server.py writes to db.py (spec.db).
                pass
            
            # For robustness, we'll write the result to latest_dashboard.json 
            # so our frontend can pick it up.
            with open("latest_dashboard.json", "w") as f:
                # We need to make sure 'result' is clean JSON.
                # If the remote server returned a PrefabApp object, result might be a string.
                # We'll try to find the JSON spec in it.
                json_start = result.find("{")
                json_end = result.rfind("}") + 1
                if json_start != -1 and json_end != -1:
                    json_str = result[json_start:json_end]
                    # Validate it's JSON
                    spec_data = json.loads(json_str)
                    # Handle the case where it might be wrapped in another key
                    if "spec" in spec_data:
                        json.dump(spec_data, f)
                    else:
                        json.dump({"spec": spec_data, "title": "MCP Dashboard"}, f)
                    
                    return f"DASHBOARD_DATA:{json_str}"
        except:
            pass
            
    return f"MCP_RESULT:{result}"


AGENT_TOOLS = [query_rag, list_topics, get_topic_stats, internet_search, create_chart, save_dashboard, generate_mcp_dashboard]

SYSTEM_PROMPT = """You are a knowledgeable research assistant with access to a personal knowledge base and the public internet.
The knowledge base contains web pages, documents, selected text, and YouTube transcripts that the user has collected.

When answering questions:
1. First, search the knowledge base using the query_rag tool.
2. If the knowledge base doesn't contain the answer or the user asks for general web info, use the internet_search tool.
3. Synthesize information from multiple sources when available.
4. **PROACTIVE VISUALIZATION**: If you find numeric data, comparisons, trends, or statistics, you SHOULD call `create_chart` or `create_dashboard` to help the user understand the data visually. Do not wait for them to ask for a chart specifically.
5. Always cite your sources (mention the URL/source or indicate it was found via web search).
6. Be concise but thorough.

If the user asks what topics are available, use list_topics.
If asked about stats for a specific topic, use get_topic_stats.
If the user asks for a graph, chart, or any data comparison, use `create_chart`.
If the user asks for a 'dashboard', 'overview', or 'summary report', you MUST call the `save_dashboard` tool.
If the user specifically asks to 'plot', create an 'interactive app', or 'use the dashboard server', call `generate_mcp_dashboard`.
You can optionally design the `widgets` yourself if you have the data ready. 
Widgets support kinds: 'stat' (label, value), 'bar' (data, x_key, y_keys), 'line' (data, x_key, y_keys), 'pie' (data, title), 'checklist' (title, items), and 'text' (heading, body).
"""


# ── Query entry point ───────────────────────────────────────────────────────
def run_query(question: str, topic: Optional[str] = None, chat_history: list = None) -> dict:
    """
    Run the LangGraph ReAct agent with an optional topic hint.
    Returns a dict with 'answer' (str) and 'tools_used' (list of str).
    """
    llm = _get_llm()
    agent = create_react_agent(llm, AGENT_TOOLS, prompt=SYSTEM_PROMPT)

    full_question = question
    if topic:
        full_question = f"[Context: focus on topic '{topic}']\n{question}"

    result = agent.invoke({"messages": [HumanMessage(content=full_question)]})

    # Extract tools, visuals, and answer
    tools_used = []
    visuals = []
    final_answer = ""
    
    for m in result["messages"]:
        # Tool calls
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                tools_used.append(tc["name"])
        
        # Visuals in tool responses
        if m.type == "tool":
            content = m.content
            if isinstance(content, str):
                if "VISUAL_DATA:" in content:
                    try:
                        start_idx = content.find("VISUAL_DATA:") + 12
                        visuals.append(json.loads(content[start_idx:]))
                    except: pass
                if "DASHBOARD_DATA:" in content:
                    try:
                        start_idx = content.find("DASHBOARD_DATA:") + 15
                        spec = json.loads(content[start_idx:])
                        visuals.append({
                            "type": "dashboard",
                            "spec": spec,
                            "title": spec.get("params", {}).get("title", "Dashboard")
                        })
                    except: pass
                if "PREFAB_SOURCE:" in content:
                    try:
                        start_idx = content.find("PREFAB_SOURCE:") + 14
                        source = content[start_idx:]
                        visuals.append({
                            "type": "prefab_source",
                            "source": source,
                            "title": "Interactive App"
                        })
                    except: pass
        
        # AI content
        if m.type == "ai" and not m.tool_calls:
            final_answer = m.content

    if not final_answer and result["messages"]:
        final_answer = result["messages"][-1].content

    return {
        "answer": final_answer,
        "tools_used": list(set(tools_used)),
        "visuals": visuals
    }
