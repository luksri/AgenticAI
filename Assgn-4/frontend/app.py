# frontend/app.py — PrefabUI Knowledge Collector Chat + Stats Dashboard
#
# Run with: prefab serve app.py --reload
# Opens at: http://127.0.0.1:5175

import httpx
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge, Button, Card, CardContent, CardHeader, CardTitle,
    Column, H3, H4, Input, Muted, Row, Text, Separator, Heading, Slot,
    DataTable, DataTableColumn, If, H1,
)
from prefab_ui.components.charts import BarChart, LineChart, AreaChart, PieChart, ScatterChart, RadarChart, ChartSeries
from prefab_ui.components.control_flow import ForEach
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.fetch import Fetch
from prefab_ui.actions.mcp import CallTool
from prefab_ui.rx import Rx, RESULT
from fastmcp import FastMCP, AppConfig

mcp = FastMCP("FrontendExecutor")

BACKEND_URL = "http://localhost:8000"


# ── Fetch initial data from backend ───────────────────────────────────────
def _fetch_initial_stats():
    try:
        r = httpx.get(f"{BACKEND_URL}/stats", timeout=3)
        return r.json()
    except Exception:
        return {"total_docs": 0, "total_topics": 0, "total_sources": 0, "topics": []}


initial_stats = _fetch_initial_stats()
initial_topics = initial_stats.get("topics", [])

# ── Reactive state ─────────────────────────────────────────────────────────
user_input   = Rx("user_input")
selected_topic = Rx("selected_topic")
messages     = Rx("messages")
stats        = Rx("stats")
topics       = Rx("topics")
is_loading   = Rx("is_loading")
dashboards   = Rx("dashboards")

# ── App ────────────────────────────────────────────────────────────────────
with PrefabApp(
    title="Knowledge Collector",
    state={
        "user_input": "",
        "selected_topic": "",
        "messages": [],
        "stats": initial_stats,
        "topics": initial_topics,
        "is_loading": False,
        "dashboards": [],
        "view_mode": "chat",
        "current_dashboard": None,
    },
    css_class="h-screen flex flex-col bg-background",
) as app:

    # ════════════════════════════════════════════════════════════════════════
    # TOP NAV BAR
    # ════════════════════════════════════════════════════════════════════════
    with Row(
        css_class=(
            "border-b px-6 py-4 items-center justify-between "
            "bg-slate-950/40 backdrop-blur-md sticky top-0 z-50 "
            "border-white/5 shadow-xl"
        ),
        gap=4,
    ):
        with Row(gap=3, css_class="items-center"):
            Heading("🧠 Knowledge Collector", level=1, css_class="text-lg font-bold")
            Badge("RAG + Gemini", variant="secondary", css_class="text-xs")

        with Row(gap=2, css_class="items-center"):
            Muted(f"Active topic:")
            Badge(
                "{{ selected_topic || 'All Topics' }}",
                variant="outline",
            )
            Button(
                "↻ Refresh",
                variant="ghost",
                css_class="text-xs",
                on_click=Fetch(
                    url=f"{BACKEND_URL}/stats",
                    method="GET",
                    on_success=[
                        SetState("stats", RESULT),
                        SetState("topics", "{{ $result.topics }}"),
                        Fetch(
                            url=f"{BACKEND_URL}/dashboards",
                            method="GET",
                            on_success=SetState("dashboards", "{{ $result.dashboards }}")
                        ),
                        ShowToast("Stats refreshed", variant="default"),
                    ],
                    on_error=ShowToast("Could not reach backend", variant="error"),
                ),
            )

    # ════════════════════════════════════════════════════════════════════════
    # MAIN CONTENT: sidebar + chat
    # ════════════════════════════════════════════════════════════════════════
    with Row(css_class="flex-1 overflow-hidden", gap=0):

        # ── LEFT SIDEBAR ──────────────────────────────────────────────────
        with Column(
            css_class=(
                "w-80 border-r flex-shrink-0 overflow-y-auto p-5 "
                "bg-slate-950/40 backdrop-blur-xl border-white/5 "
                "shadow-[20px_0_50px_-20px_rgba(0,0,0,0.5)]"
            ),
            gap=6,
        ):
            # Stats cards
            H4("📊 Knowledge Base Stats", css_class="font-semibold text-sm text-muted-foreground uppercase tracking-wide")

            with Column(gap=3):
                # Total Docs
                with Card(css_class="border-violet-500/20 bg-violet-950/20"):
                    with CardContent(css_class="p-4 flex items-center gap-3"):
                        Text("📄", css_class="text-2xl")
                        with Column(gap=0):
                            Text(
                                "{{ stats.total_docs || 0 }}",
                                css_class="text-3xl font-bold text-violet-300",
                            )
                            Muted("Total Documents")

                # Topics count
                with Card(css_class="border-purple-500/20 bg-purple-950/20"):
                    with CardContent(css_class="p-4 flex items-center gap-3"):
                        Text("🗂️", css_class="text-2xl")
                        with Column(gap=0):
                            Text(
                                "{{ stats.total_topics || 0 }}",
                                css_class="text-3xl font-bold text-purple-300",
                            )
                            Muted("Topics")

                # Sources count
                with Card(css_class="border-pink-500/20 bg-pink-950/20"):
                    with CardContent(css_class="p-4 flex items-center gap-3"):
                        Text("🔗", css_class="text-2xl")
                        with Column(gap=0):
                            Text(
                                "{{ stats.total_sources || 0 }}",
                                css_class="text-3xl font-bold text-pink-300",
                            )
                            Muted("Unique Sources")

            Separator()

            # Topic filter
            H4("🗂️ Topics", css_class="font-semibold text-sm text-muted-foreground uppercase tracking-wide")

            Button(
                "🌐 All Topics",
                variant="ghost",
                css_class="w-full justify-start text-sm font-medium",
                on_click=[
                    SetState("selected_topic", ""),
                    SetState("view_mode", "chat")
                ],
            )

            with ForEach("topics"):
                with Card(css_class="cursor-pointer hover:bg-accent transition-colors"):
                    with CardContent(
                        css_class="p-3",
                        on_click=[
                            SetState("selected_topic", "{{ $item.name }}"),
                            SetState("view_mode", "chat")
                        ],
                    ):
                        with Row(css_class="items-center justify-between", gap=2):
                            with Row(gap=2, css_class="items-center"):
                                Text("📁", css_class="text-sm")
                                Text("{{ $item.name }}", css_class="text-sm font-medium truncate")
                            with Column(gap=0, css_class="items-end flex-shrink-0"):
                                Badge("{{ $item.doc_count }} docs", variant="secondary", css_class="text-xs")
                                Muted("{{ $item.source_count }} srcs", css_class="text-xs")

            Separator()

            # Saved Dashboards
            H4("📊 Dashboards", css_class="font-semibold text-sm text-muted-foreground uppercase tracking-wide")
            
            with ForEach("dashboards"):
                with Card(css_class="cursor-pointer hover:bg-accent transition-colors mb-2"):
                    with CardContent(
                        css_class="p-3",
                        on_click=[
                            SetState("current_dashboard", "{{ $item }}"),
                            SetState("view_mode", "dashboard")
                        ]
                    ):
                        with Row(css_class="items-center justify-between", gap=2):
                            with Row(gap=2, css_class="items-center"):
                                Text("📈", css_class="text-sm")
                                Text("{{ $item.title }}", css_class="text-sm font-medium truncate")
                            
                            with Row(gap=1, css_class="items-center"):
                                Badge("{{ $item.topic || 'General' }}", variant="outline", css_class="text-[9px]")
                                # Quick delete in sidebar
                                Button(
                                    "×",
                                    variant="ghost",
                                    css_class="h-5 w-5 p-0 text-muted-foreground hover:text-destructive",
                                    on_click=Fetch(
                                        url=f"{BACKEND_URL}/dashboards/{{{{ $item.id }}}}",
                                        method="DELETE",
                                        on_success=[
                                            Fetch(
                                                url=f"{BACKEND_URL}/dashboards",
                                                method="GET",
                                                on_success=SetState("dashboards", "{{ $result.dashboards }}")
                                            ),
                                            ShowToast("Dashboard deleted")
                                        ]
                                    )
                                )

        # ── MAIN AREA ──────────────────────────────────────────────────────
        with Column(css_class="flex-1 flex flex-col overflow-hidden", gap=0):
            
            # ── CHAT VIEW ──
            with Column(css_class="{{ view_mode == 'chat' ? 'flex' : 'hidden' }} flex-1 flex flex-col overflow-hidden", gap=0):

                # Chat header
                with Row(
                    css_class="border-b px-6 py-3 items-center justify-between bg-slate-950/30",
                    gap=3,
                ):
                    with Row(gap=3, css_class="items-center"):
                        Text("💬", css_class="text-lg")
                        H3("Chat with your Knowledge Base", css_class="font-semibold")
                        Badge(
                            "{{ selected_topic ? ('Topic: ' + selected_topic) : 'All Topics' }}",
                            variant="outline",
                            css_class="text-xs",
                        )
                    
                    Button(
                        "🗑️ Clear Chat",
                        variant="ghost",
                        css_class="text-xs text-muted-foreground hover:text-destructive transition-colors",
                        on_click=[
                            SetState("messages", []),
                            ShowToast("Chat history cleared")
                        ]
                    )

                # ── Message history ──
                with Column(
                    css_class="flex-1 overflow-y-auto p-6 space-y-4",
                    gap=4,
                ):
                    # Empty state
                    with Column(
                        css_class="{{ messages.length > 0 ? 'hidden' : 'flex items-center justify-center h-full' }}",
                        gap=3,
                    ):
                        Text("🧠", css_class="text-5xl text-center")
                        H3("Ask your Knowledge Base", css_class="text-center text-muted-foreground")
                        Muted("Use the Chrome extension to collect content, then ask questions here.", css_class="text-center text-sm")

                    with ForEach("messages"):
                        with Row(
                            css_class="{{ $item.role == 'user' ? 'justify-end' : 'justify-start' }}",
                            gap=2,
                        ):
                            with Card(
                                css_class="{{ $item.role == 'user' ? 'max-w-lg bg-violet-600/20 border-violet-500/40 shadow-[0_0_20px_rgba(139,92,246,0.1)]' : 'max-w-2xl bg-slate-900/40 border-white/5 backdrop-blur-sm' }}"
                            ):
                                with CardContent(css_class="p-4"):
                                    with Row(gap=2, css_class="items-center mb-2"):
                                        Text(
                                            "{{ $item.role == 'user' ? '👤 You' : '🤖 Assistant' }}",
                                            css_class="text-xs font-semibold text-muted-foreground",
                                        )
                                        # Tool markers
                                        with Row(gap=1, css_class="{{ $item.tools_used && $item.tools_used.length > 0 ? 'flex' : 'hidden' }}"):
                                            with ForEach("$item.tools_used"):
                                                Badge("🛠️ {{ $item }}", variant="outline", css_class="text-[9px] py-0 px-1 h-4 opacity-50")
                                    Text("{{ $item.content }}", css_class="text-sm whitespace-pre-wrap leading-relaxed")
                                    
                                    # Visualization Section
                                    with ForEach("$item.visuals", as_variable="visual"):
                                        with Column(css_class="mt-4 p-4 border rounded-lg bg-slate-900/50", gap=2):
                                            with Row(justify="between", items="center"):
                                                Heading("{{ visual.title }}", size="sm")
                                                Badge("{{ visual.chart_type }} chart", variant="outline")
                                            
                                            with Column(css_class="min-h-[250px] items-center justify-center"):
                                                # Bar Chart
                                                with If("visual.chart_type == 'bar'"):
                                                    BarChart(
                                                        data="{{ visual.data }}",
                                                        series=[ChartSeries(data_key="{{ visual.y }}", label="{{ visual.title || visual.y }}")],
                                                        x_axis="{{ visual.x }}",
                                                        css_class="w-full h-64"
                                                    )
                                                # Line Chart
                                                with If("visual.chart_type == 'line'"):
                                                    LineChart(
                                                        data="{{ visual.data }}",
                                                        series=[ChartSeries(data_key="{{ visual.y }}", label="{{ visual.title || visual.y }}")],
                                                        x_axis="{{ visual.x }}",
                                                        css_class="w-full h-64"
                                                    )
                                                # Pie Chart
                                                with If("visual.chart_type == 'pie'"):
                                                    PieChart(
                                                        data="{{ visual.data }}",
                                                        data_key="{{ visual.y }}",
                                                        name_key="{{ visual.x }}",
                                                        css_class="w-full h-64"
                                                    )
                                                
                                                # Fallback Data Table
                                                with If("visual.type == 'chart'"):
                                                    with Column(css_class="mt-2 w-full"):
                                                        Muted("Data Preview:", css_class="text-[10px] mb-1")
                                                        DataTable(
                                                            columns=[
                                                                DataTableColumn(key="{{ visual.x }}", header="{{ visual.x }}"),
                                                                DataTableColumn(key="{{ visual.y }}", header="{{ visual.y }}"),
                                                            ],
                                                            rows="{{ visual.data }}",
                                                            css_class="text-xs"
                                                        )
                                                
                                                # Dashboard Rendering
                                                with If("visual.type == 'dashboard'"):
                                                    with Column(css_class="w-full", gap=4):
                                                        # We'll use a simplified version of the renderer here
                                                        # since we can't easily do nested ForEach over complex logic in the static tree
                                                        # Instead, we'll show the title and the first tab's widgets as a summary
                                                        H4("{{ visual.spec.params.title }}", css_class="text-center border-b pb-2")
                                                        with Row(gap=2, css_class="justify-center flex-wrap"):
                                                            with ForEach("visual.spec.params.tabs"):
                                                                Badge("{{ name }}", variant="secondary")
                                                        
                                                        # Note: Rendering the full multi-tab dashboard inside a chat bubble 
                                                        # is complex. In a real app, you'd navigate to a full-screen view.
                                                        # For now, we'll indicate it can be opened.
                                                        Button("Open Full Dashboard", variant="outline", css_class="w-full")

                    # Dynamic answer slot (shown while streaming)
                    Slot("chat_answer")

                # ── Input area ──
                with Row(
                    css_class="border-t p-4 bg-slate-950/30",
                    gap=3,
                ):
                    Input(
                        name="user_input",
                        placeholder="Ask anything about your collected knowledge…",
                        css_class="flex-1",
                        on_change=SetState("user_input", "{{ $event }}"),
                        on_key_down=[
                            # Send on Enter
                            Fetch(
                                url=f"{BACKEND_URL}/query",
                                method="POST",
                                body={
                                    "query": "{{ user_input }}",
                                    "topic": "{{ selected_topic || null }}",
                                    "messages": "{{ messages }}",
                                },
                                on_success=[
                                    SetState(
                                        "messages",
                                        "{{ $result.new_messages }}",
                                    ),
                                    SetState("user_input", ""),
                                ],
                                on_error=ShowToast("Agent error: {{ $error }}", variant="error"),
                            ),
                        ] if False else [],  # key_down wiring; use button for now
                    )
                    Button(
                        "{{ is_loading ? '⏳ Thinking…' : 'Send ➤' }}",
                        variant="default",
                        css_class="px-6 bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500",
                        on_click=[
                            SetState("is_loading", True),
                            Fetch(
                                url=f"{BACKEND_URL}/query",
                                method="POST",
                                body={
                                    "query": "{{ user_input }}",
                                    "topic": "{{ selected_topic || null }}",
                                    "messages": "{{ messages }}",
                                },
                                on_success=[
                                    SetState("messages", "{{ $result.new_messages }}"),
                                    SetState("user_input", ""),
                                    SetState("is_loading", False),
                                    # Fetch latest dashboard and switch view if one was just saved
                                    Fetch(
                                        url=f"{BACKEND_URL}/latest_dashboard",
                                        method="GET",
                                        on_success=[
                                            SetState("current_dashboard", RESULT),
                                            SetState("view_mode", "dashboard")
                                        ]
                                    )
                                ],
                                on_error=[
                                    ShowToast("Agent error: {{ $error }}", variant="error"),
                                    SetState("is_loading", False),
                                ],
                            ),
                        ],
                    )
            
            # ── DASHBOARD VIEW (Dynamic Executor) ──
            with Column(css_class="{{ view_mode == 'dashboard' ? 'flex' : 'hidden' }} flex-1 flex flex-col overflow-y-auto p-8", gap=6):
                with Row(justify="between", align="center"):
                    with Column(gap=1):
                        H1("{{ current_dashboard.title || 'Interactive App' }}", css_class="text-3xl font-bold")
                        Muted("Topic: {{ current_dashboard.topic || 'General' }}")
                    
                    with Row(gap=2):
                        Button(
                            "🗑️ Delete",
                            variant="destructive",
                            on_click=Fetch(
                                url=f"{BACKEND_URL}/dashboards/{{{{ current_dashboard.id }}}}",
                                method="DELETE",
                                on_success=[
                                    SetState("view_mode", "chat"),
                                    Fetch(
                                        url=f"{BACKEND_URL}/dashboards",
                                        method="GET",
                                        on_success=SetState("dashboards", "{{ $result.dashboards }}")
                                    ),
                                    ShowToast("Dashboard deleted")
                                ]
                            )
                        )
                        Button(
                            "← Back to Chat", 
                            variant="outline", 
                            on_click=SetState("view_mode", "chat")
                        )
                
                Separator()

                # THE DYNAMIC LOADER
                with If("current_dashboard.spec.source"):
                    with Column(gap=4, css_class="items-center justify-center p-20 border-2 border-dashed border-white/10 rounded-2xl bg-white/5"):
                        Text("🚀 Ready to launch dynamic dashboard", css_class="text-xl font-medium")
                        Button(
                            "Launch Interactive Dashboard",
                            variant="default",
                            css_class="px-10 h-12 bg-gradient-to-r from-violet-600 to-blue-600",
                            on_click=CallTool(
                                "execute_dynamic_app",
                                arguments={"source": "{{ current_dashboard.spec.source }}"}
                            )
                        )
                
                with If("!current_dashboard.spec.source"):
                    with Column(gap=4, css_class="items-center justify-center p-20 opacity-50"):
                        Text("⚠️ No dynamic source found for this dashboard.", css_class="text-lg")
                        Muted("Falling back to basic view...")

    # ── Internal Tool to Execute the Source ──
    @mcp.tool(app=AppConfig(visibility=["app"]))
    def execute_dynamic_app(source: str) -> PrefabApp:
        """Executes raw PrefabUI source code and returns the resulting app."""
        try:
            # Prepare execution environment
            exec_globals = globals().copy()
            # The template always defines a function 'dummy_app'
            exec(source, exec_globals)
            return exec_globals["dummy_app"]()
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return ShowToast(f"Execution error: {str(e)}", variant="error")
