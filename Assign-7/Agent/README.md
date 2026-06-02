# Assignment 6 — agent6: Modular Four-Role Agentic Loop

A fully typed, modular AI agent built around a clean four-role architecture: **Memory → Perception → Decision → Action**. Each role has a single well-defined responsibility and a typed boundary contract, wired together by a central async loop with a live MCP tool server.

---

## Architecture Overview

```
User Query
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        agent6 Loop (agent.py)                       │
│                                                                     │
│  ┌──────────┐    ┌─────────────┐    ┌──────────┐    ┌──────────┐   │
│  │  Memory  │───▶│  Perception │───▶│ Decision │───▶│  Action  │   │
│  │ (read)   │    │ (observe)   │    │(next_step│    │(execute) │   │
│  └──────────┘    └─────────────┘    └──────────┘    └──────────┘   │
│       ▲                                                   │         │
│       └────────── record_outcome() ◀──────────────────────┘         │
└─────────────────────────────────────────────────────────────────────┘
         │                                           │
         ▼                                           ▼
  sandbox/state/memory.json              MCP Server (mcp_server.py)
                                         9 tools via stdio transport
```

The loop runs up to `MAX_ITERATIONS = 10` times. Each iteration:
1. **Memory.read** — recall relevant facts/outcomes from durable store (pure keyword search, no LLM)
2. **Perception.observe** — decompose query into goals, track done flags, attach artifacts
3. **Decision.next_step** — pick the next action: either a direct answer or a single MCP tool call
4. **Action.execute** — dispatch the tool via MCP, offload large results to the artifact store

The loop exits early as soon as Perception marks all goals done.

---

## Role Contracts

| Role | File | Returns | LLM call? |
|---|---|---|---|
| **Memory** | `memory.py` | `list[MemoryItem]` | Only on `remember()` write |
| **Perception** | `perception.py` | `Observation` (goals + done flags) | Yes — pinned to Gemini |
| **Decision** | `decision.py` | `DecisionOutput` (answer OR tool_call) | Yes — auto-routed |
| **Action** | `action.py` | `tuple[str, str \| None]` (descriptor, artifact_id) | **None** — pure dispatch |

Typed schemas (`schemas.py`) enforce these boundaries at every role transition via Pydantic models.

---

## Memory Design

Memory is a **typed service** — not a simple string list. It stores four kinds of items:

| Kind | Description | Example |
|---|---|---|
| `fact` | A durable observed truth | `"John's birthday is 15 May 2026"` |
| `preference` | A user-stated or inferred preference | `"User prefers metric units"` |
| `tool_outcome` | Result of an MCP tool call | Web search results, currency rates |
| `scratchpad` | Run-scoped working note | Intermediate computation |

**Reads** are pure Python keyword intersection — fast enough to run before every Perception call with no LLM cost. **Writes** via `remember()` make a single LLM gateway call to classify and extract structured keywords, making all future reads cheap.

All items persist in `sandbox/state/memory.json` and survive across runs. Facts and preferences accumulate; scratchpad items are scoped per run.

---

## Artifact Store

When a tool result exceeds **4 KB**, the bytes are pushed to a content-addressable artifact store (`artifacts.py`) rather than inline history. Memory holds only the handle (`art:<sha256-prefix>`). Perception can attach artifact bytes to a goal by setting `attach_artifact_id`, and Decision receives a 2000-char text preview of the blob — keeping token budgets bounded while still allowing large document processing.

---

## MCP Tool Server

`mcp_server.py` exposes **9 tools** over stdio transport:

| Tool | Description |
|---|---|
| `web_search` | Tavily (primary) + DuckDuckGo fallback; hard-capped at 5 results |
| `fetch_url` | Clean markdown from any URL via crawl4ai headless Chromium |
| `get_time` | Current time in any IANA timezone |
| `currency_convert` | Live FX rates via frankfurter.dev; no API key needed |
| `read_file` | Read a UTF-8 file from the sandbox |
| `list_dir` | List a sandbox directory |
| `create_file` | Create a new sandbox file (errors if exists) |
| `update_file` | Overwrite an existing sandbox file |
| `edit_file` | Find-and-replace inside a sandbox file |

All file tools are sandboxed under `./sandbox/` — path traversal is blocked at the `_safe()` boundary.

Tavily usage is logged to `usage.json` with a monthly rollover and a soft cap of 950/1000 calls.

---

## LLM Gateway (V3)

All LLM calls route through the **LLM Gateway V3** at `http://localhost:8101`.

- **`auto_route`** — carries `"perception"`, `"memory"`, or `"decision"`. A small router LLM classifies the token budget and picks a TINY / LARGE / HUGE tier worker. The router sees only `{token_count, sample}` — agentic context is never leaked.
- **Provider override** — `provider="g"` pins Perception and Memory calls to Gemini, bypassing the router. Used because empirical testing showed the TINY-tier router was too small to reliably follow Perception's multi-step procedure.
- **`response_format`** — structured JSON output validated server-side against a JSON Schema. Perception and Memory both use this; callers receive an already-validated parsed dict.

---

## Prompt Design (prompt_rules.txt)

Every LLM-facing system prompt in this project is evaluated against a prompt quality rubric covering 9 criteria:

1. Explicit step-by-step reasoning instructions
2. Structured output format (JSON schema-enforced)
3. Separation of reasoning and tool-use steps
4. Conversation loop support (history + prior goals every call)
5. Instructional framing with format templates
6. Internal self-checks before writing output
7. Reasoning-type awareness (LOOKUP / COMPUTE / FETCH / FILE tagging)
8. Error handling and fallbacks
9. Overall clarity and hallucination resistance

Both `perception.py` and `decision.py` include a ✓ checklist confirming compliance.

---

## Project Structure

```
Assign-6/
├── agent.py          # Main loop — wires all four roles
├── perception.py     # Role 1: Goal decomposition & tracking
├── decision.py       # Role 2: Answer vs. tool-call selection
├── action.py         # Role 3: MCP dispatch & artifact offload
├── memory.py         # Role 4: Typed durable memory service
├── mcp_server.py     # 9 MCP tools over stdio
├── artifacts.py      # Content-addressable blob store
├── schemas.py        # Pydantic boundary models
├── prompt_rules.txt  # Prompt evaluation rubric
├── queries_to_test.txt  # Example queries
├── llm_gatewayV3/    # LLM Gateway V3 (must be started separately)
├── sandbox/          # Sandboxed file workspace + memory.json
└── .env              # API keys (TAVILY_API_KEY)
```

---

## Setup

### Prerequisites

- Python 3.11+
- A `.env` file in `Assign-6/` with your Tavily key (optional — DuckDuckGo fallback works without it):
  ```
  TAVILY_API_KEY=tvly-...
  ```
- Install dependencies (ideally inside `.venv`):
  ```bash
  pip install mcp httpx pydantic python-dotenv tavily-python crawl4ai ddgs
  ```

### Start the LLM Gateway

The gateway **must be running** before `agent.py` is invoked:

```bash
cd llm_gatewayV3
./run.sh
```

The gateway listens on `http://localhost:8101`. `agent.py` performs a health-check at startup and raises a clear error if it is not reachable.

---

## Running the Agent

```bash
python agent.py "Your question here"
```

### Example Queries

```bash
# Multi-step web research + artifact processing
python agent.py "Fetch https://en.wikipedia.org/wiki/Claude_Shannon and tell me his birth date, death date, and three key contributions to information theory."

# Weather-aware recommendation
python agent.py "Find 3 family-friendly things to do in Tokyo this weekend. Check Saturday's weather forecast there and tell me which one is most appropriate."

# Durable memory persistence
python agent.py "My mom's birthday is 15 May 2026. Remember that and give me a calendar reminder for two weeks before and on the day."

# Memory recall across runs
python agent.py "When is mom's birthday?"

# Synthesis across multiple sources
python agent.py "Search for 'Python asyncio best practices', read the top 3 results, and give me a short numbered list of the advice they agree on."
```

### Console Output Format

Each iteration prints a structured trace:

```
─── iter 1 ───
[memory.read]   2 hits
                fact: "Mom's birthday is 15 May 2026"
[perception]    [progress] Recall mom's birthday from memory
[decision]      ANSWER: Mom's birthday is 15 May 2026...

─── iter 2 ───
[perception]    [done] Recall mom's birthday from memory
[done] all 1 goals satisfied

FINAL: Mom's birthday is 15 May 2026...
```

---

## Key Design Decisions

- **Monotone done flag** — once Perception marks a goal `done=True`, no subsequent LLM call can un-done it. Enforced in `Perception._parse_goals()`.
- **No duplicate tool calls** — Decision checks history and refuses to call a tool with identical arguments twice in one run.
- **Token budget** — both Perception and Decision receive only the last 20 history events to bound LLM input size.
- **Non-fatal memory** — if the gateway is unavailable on startup, `memory.remember()` fails silently and the agent continues. Memory is useful but not load-bearing for a single run.
- **Artifact hallucination guard** — if Perception emits an `attach_artifact_id` that does not exist in the store, the loop drops it silently (`artifacts.exists()` gate in `agent.py`).

---

## Architecture Diagrams

| Diagram | File |
|---|---|
| Full loop flow | `flow_diag.png` |
| Memory kinds | `memory_kinds.png` |
| Memory read operations | `memory_read_ops.png` |
| Memory write operations | `memory_writes.png` |
| Module architecture | `arch.png` |
