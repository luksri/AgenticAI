# Knowledge Collector — Assignment 4

A three-part system to stream web content into a local RAG knowledge base and chat with it via Gemini.

---

## Components

```
Assgn-4/
├── extension/     # Chrome Extension (Manifest V3)
├── backend/       # FastAPI + FastMCP + ChromaDB + Gemini Agent
└── frontend/      # PrefabUI chat + stats dashboard
```

---

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# Start the server (port 8000)
python main.py
```

### 2. Frontend (PrefabUI)

```bash
cd frontend
pip install prefab-ui   # if not already installed
prefab serve app.py --reload
# Opens at http://127.0.0.1:5175
```

### 3. Chrome Extension

1. Open `chrome://extensions`
2. Enable **Developer Mode** (top right)
3. Click **Load unpacked** → select the `extension/` folder
4. Click the 🧠 icon in the toolbar to set your active topic

---

## Usage

### Collecting Content

Right-click on any webpage and choose:
- **📝 Send selected text** — sends highlighted text
- **🌐 Send this page** — scrapes the full page (also works for PDFs from the web)
- **▶️ Send YouTube video** — fetches the transcript (on YouTube pages)

The popup lets you:
- Set / change the active topic
- See the last ingestion status
- Browse existing topics and click to switch

### Chatting

Open the PrefabUI frontend at `http://localhost:5175`. You can:
- Ask questions across **all topics** (default)
- Filter to a **specific topic** by clicking it in the sidebar
- See live stats: total docs, topics, and sources

---

## YouTube MCP Integration

To use an external YouTube MCP server instead of the built-in transcript fallback:

1. Edit `backend/mcp_config.py`
2. Set `"enabled": True` and fill in `command`, `args`, and `YOUTUBE_API_KEY`
3. Implement the call in `ingest.py → _ingest_youtube_via_mcp()`

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | Google Gemini API key |
| `BACKEND_PORT` | `8000` | FastAPI server port |
| `CHROMA_DB_PATH` | `./chroma_db` | Local ChromaDB storage path |

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Backend health check |
| `/ingest` | POST | Receive data from Chrome extension |
| `/topics` | GET | List all topics (used by popup) |
| `/stats` | GET | Global stats (docs, topics, sources) |
| `/query` | POST | Run Gemini agent query |
| `/mcp` | — | FastMCP endpoint (for MCP hosts) |
