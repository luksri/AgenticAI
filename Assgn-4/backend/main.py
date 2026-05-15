# main.py — FastAPI + FastMCP server for Knowledge Collector

import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge, Button, Card, CardContent, CardHeader, CardTitle,
    Column, H3, Input, Muted, Row, Text, Separator, Slot,
)
from prefab_ui.components.control_flow import ForEach
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.rx import Rx, RESULT

import rag
import ingest as ingest_module
import agent as agent_module
import dashboard_db


# ── FastMCP server ─────────────────────────────────────────────────────────
mcp = FastMCP("knowledge-collector")


# ── FastAPI app ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    dashboard_db.init_db()
    print("✅ Knowledge Collector backend started")
    yield
    print("🛑 Knowledge Collector backend stopped")

api = FastAPI(
    title="Knowledge Collector API",
    description="RAG backend for the Knowledge Collector Chrome extension",
    version="1.0.0",
    lifespan=lifespan,
)

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ────────────────────────────────────────────────────────
class IngestRequest(BaseModel):
    type: str               # "text" | "page" | "youtube"
    topic: str
    source: str
    content: Optional[str] = None   # for type=text or type=page (fallback)
    url: Optional[str] = None       # for type=page or type=youtube
    title: Optional[str] = None


class QueryRequest(BaseModel):
    query: str
    topic: Optional[str] = None
    chat_history: Optional[list] = None
    messages: list[dict] = []


# ── REST Endpoints ─────────────────────────────────────────────────────────
@api.get("/health")
async def health():
    return {"status": "ok"}


@api.post("/ingest")
async def ingest_endpoint(req: IngestRequest):
    """Receive data from the Chrome extension and store in ChromaDB."""
    try:
        result = await ingest_module.ingest_content(
            content_type=req.type,
            topic=req.topic,
            source=req.source,
            content=req.content,
            url=req.url,
            title=req.title,
        )
        doc_count = rag.add_documents(
            topic=req.topic,
            chunks=result["chunks"],
            source=result["source"],
            title=result["title"],
        )
        return {
            "status": "ok",
            "topic": req.topic,
            "chunks_added": len(result["chunks"]),
            "doc_count": doc_count,
            "title": result["title"],
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")


@api.get("/topics")
async def topics_endpoint():
    """List all topics with doc counts (used by extension popup)."""
    return {"topics": rag.list_topics()}


@api.get("/stats")
async def stats_endpoint():
    """Global stats for the PrefabUI dashboard."""
    return rag.get_stats()


@api.post("/query")
async def query_endpoint(req: QueryRequest):
    """Run the Gemini agent against the RAG knowledge base."""
    print(f"\n[QUERY] Received query: {req.query}")
    print(f"[QUERY] Topic constraint: {req.topic}")
    try:
        query_result = agent_module.run_query(
            question=req.query,
            topic=req.topic,
            chat_history=req.chat_history,
        )
        answer = query_result["answer"]
        tools_used = query_result["tools_used"]
        visuals = query_result.get("visuals", [])
        print(f"[QUERY] Agent Answer: {answer}\n")
        
        # Build the new messages array in Python to avoid frontend JS evaluation issues
        new_messages = req.messages + [
            {"role": "user", "content": req.query},
            {"role": "assistant", "content": answer, "tools_used": tools_used, "visuals": visuals}
        ]

        # Save any dashboards to the database
        for vis in visuals:
            if vis.get("type") == "dashboard":
                dashboard_db.save_dashboard(
                    spec=vis["spec"],
                    topic=req.topic,
                    title=vis.get("title", "Generated Dashboard")
                )

        return {"answer": answer, "new_messages": new_messages, "tools_used": tools_used, "visuals": visuals}
    except Exception as e:
        print(f"[QUERY] Error: {e}\n")
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")


@api.get("/latest_dashboard")
async def get_latest_dashboard():
    if not os.path.exists("latest_dashboard.json"):
        return {"error": "No dashboard generated yet"}
    try:
        with open("latest_dashboard.json", "r") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


@api.get("/dashboards")
async def get_dashboards(topic: Optional[str] = None):
    return {"dashboards": dashboard_db.get_dashboards(topic)}


@api.post("/dashboards/save")
async def save_dashboard_endpoint(req: dict):
    dashboard_db.save_dashboard(
        spec=req["spec"],
        topic=req.get("topic"),
        title=req.get("title", "Untitled Dashboard")
    )
    return {"status": "ok"}


@api.delete("/dashboards/{id}")
async def delete_dashboard_endpoint(id: int):
    dashboard_db.delete_dashboard(id)
    return {"status": "ok"}


# ── MCP Tools (exposed via FastMCP) ────────────────────────────────────────
@mcp.tool(app=True)
def knowledge_chat() -> PrefabApp:
    """Open the Knowledge Collector chat UI — query your knowledge base."""
    selected_topic = Rx("selected_topic")
    user_input = Rx("user_input")
    messages = Rx("messages")
    stats = Rx("stats")
    topics = Rx("topics")

    with PrefabApp(
        title="Knowledge Collector",
        state={
            "selected_topic": "",
            "user_input": "",
            "messages": [],
            "stats": {},
            "topics": [],
        },
    ) as app:
        with Row(gap=0, css_class="h-screen"):
            # ── Left sidebar: stats + topic picker
            with Column(css_class="w-64 border-r bg-muted/30 p-4", gap=4):
                H3("📊 Knowledge Base")
                Separator()
                # Stats cards
                with Column(gap=2):
                    with Card():
                        with CardContent(css_class="p-3"):
                            Muted("Total Docs")
                            Text(f"{{{{ stats.total_docs | default(0) }}}}", css_class="text-2xl font-bold")
                    with Card():
                        with CardContent(css_class="p-3"):
                            Muted("Topics")
                            Text(f"{{{{ stats.total_topics | default(0) }}}}", css_class="text-2xl font-bold")
                    with Card():
                        with CardContent(css_class="p-3"):
                            Muted("Sources")
                            Text(f"{{{{ stats.total_sources | default(0) }}}}", css_class="text-2xl font-bold")

                Separator()
                Muted("Filter by topic (optional)")
                with ForEach("topics"):
                    Button(
                        "{{ name }} ({{ doc_count }})",
                        on_click=SetState("selected_topic", "{{ name }}"),
                        css_class="w-full justify-start text-sm",
                        variant="ghost",
                    )
                Button(
                    "All topics",
                    on_click=SetState("selected_topic", ""),
                    css_class="w-full justify-start text-sm text-muted-foreground",
                    variant="ghost",
                )

            # ── Right: chat
            with Column(css_class="flex-1 flex flex-col", gap=0):
                # Chat header
                with CardHeader(css_class="border-b px-6 py-3"):
                    with Row(gap=2):
                        H3("💬 Chat with your Knowledge Base")
                        Badge(
                            f"Topic: {{{{ selected_topic | default('All') }}}}",
                            variant="secondary",
                        )

                # Message history
                with Column(css_class="flex-1 overflow-y-auto p-6", gap=3):
                    with ForEach("messages"):
                        with Card(css_class="{{ role == 'user' and 'ml-12 bg-primary/10' or 'mr-12' }}"):
                            with CardContent(css_class="p-3"):
                                Muted("{{ role == 'user' and 'You' or '🤖 Assistant' }}")
                                Text("{{ content }}", css_class="mt-1 whitespace-pre-wrap")

                    Slot("answer_slot")

                # Input area
                with Row(css_class="border-t p-4", gap=2):
                    Input(
                        name="user_input",
                        placeholder="Ask anything about your knowledge base…",
                        css_class="flex-1",
                        on_change=SetState("user_input", "{{ $event }}"),
                    )
                    Button(
                        "Send ➤",
                        variant="default",
                        on_click=[
                            CallTool(
                                "query_knowledge",
                                arguments={
                                    "query": user_input,
                                    "topic": selected_topic,
                                },
                                on_success=[
                                    SetState("messages", "{{ messages + [{'role': 'user', 'content': user_input}, {'role': 'assistant', 'content': $result.answer}] }}"),
                                    SetState("user_input", ""),
                                ],
                                on_error=ShowToast("{{ $error }}", variant="error"),
                            ),
                        ],
                    )

    return app


@mcp.tool(app=True)
def toggle_dashboard_item(dashboard_id: int, uid: int, idx: int) -> PrefabApp:
    """Toggle a checkbox in a specific dashboard and persist."""
    # Find the dashboard
    dashboards = dashboard_db.get_dashboards()
    match = next((d for d in dashboards if d["id"] == dashboard_id), None)
    if not match:
        return ShowToast(f"Dashboard {dashboard_id} not found", variant="error")
    
    spec = match["spec"]
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
        dashboard_db.save_dashboard(spec, topic=match["topic"], title=match["title"])
        # Actually we should update the existing record, but our simple DB just inserts. 
        # I'll fix the DB later to support updates if needed.
    
    return knowledge_chat()


@mcp.tool(app=AppConfig(visibility=["app"]))
def query_knowledge(query: str, topic: str = "") -> PrefabApp:
    """Internal tool: called from UI to run agent query. Returns answer as PrefabApp."""
    answer = agent_module.run_query(question=query, topic=topic or None)
    stats = rag.get_stats()
    topics_list = stats.get("topics", [])

    with Column(gap=2) as view:
        Text(answer, css_class="whitespace-pre-wrap")

    return PrefabApp(
        view=view,
        state={"answer": answer, "stats": stats, "topics": topics_list},
    )


@mcp.tool(app=AppConfig(visibility=["app"]))
def refresh_stats() -> PrefabApp:
    """Internal tool: refresh stats and topics list in the sidebar."""
    stats = rag.get_stats()
    topics_list = stats.get("topics", [])

    return PrefabApp(
        view=Text(""),
        state={"stats": stats, "topics": topics_list},
    )


# ── Mount FastMCP as ASGI sub-app ──────────────────────────────────────────
# FastMCP exposes an ASGI app; mount it under /mcp
mcp_asgi = mcp.http_app(path="/mcp")
api.mount("/mcp", mcp_asgi)


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if os.getenv("MCP_MODE") == "true":
        # Run as a clean MCP server (stdio) for Claude
        mcp.run()
    else:
        # Run as a full Web API for Streamlit/PrefabUI
        import uvicorn
        port = int(os.getenv("BACKEND_PORT", "8000"))
        uvicorn.run("main:api", host="0.0.0.0", port=port, reload=True)
