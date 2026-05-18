"""
agent.py — The agent6 loop.

Wires together all four roles:
    Memory → Perception → Decision → Action

Entry point:
    python agent.py "your question here"
    asyncio.run(run("your question here"))  # from another module

Prerequisites (must be running before this script):
    1. LLM gateway V3  at http://localhost:8101
       cd llm_gatewayV3 && ./run.sh
    2. .env file in this directory with TAVILY_API_KEY (optional but needed
       for web_search).  currency_convert and get_time work without keys.

Loop behaviour:
    - Max MAX_ITERATIONS iterations (hard cap prevents infinite loops).
    - Each iteration: read memory → perceive → decide → act.
    - Loop exits early when Perception marks all goals done.
    - final_answer_from() collects all answer events from history and returns
      the last one (most recent Perception-confirmed answer).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# ---------------------------------------------------------------------------
# Role imports
# ---------------------------------------------------------------------------

from action import action
from artifacts import artifacts
from decision import decision
from memory import memory
from perception import perception
from schemas import Goal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ITERATIONS   = 10
GATEWAY_URL      = "http://localhost:8101"
GATEWAY_TIMEOUT  = 5.0   # seconds for health-check
MCP_SERVER_PATH  = Path(__file__).parent / "mcp_server.py"

# ---------------------------------------------------------------------------
# Gateway health-check
# ---------------------------------------------------------------------------

def ensure_gateway() -> None:
    """
    Verify the LLM gateway is reachable. Raises RuntimeError if not.
    """
    try:
        r = httpx.get(f"{GATEWAY_URL}/v1/capabilities", timeout=GATEWAY_TIMEOUT)
        r.raise_for_status()
    except Exception as exc:
        raise RuntimeError(
            f"LLM gateway not reachable at {GATEWAY_URL}.\n"
            f"Start it with:  cd llm_gatewayV3 && ./run.sh\n"
            f"Error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# MCP session context manager
# ---------------------------------------------------------------------------

@asynccontextmanager
async def mcp_session() -> AsyncIterator[ClientSession]:
    """
    Spawn mcp_server.py as a subprocess and yield a live ClientSession.
    The process is killed when the context exits.
    """
    python = sys.executable
    params = StdioServerParameters(
        command=python,
        args=[str(MCP_SERVER_PATH)],
        env=None,   # inherits parent env (includes .env variables via load_dotenv)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


# ---------------------------------------------------------------------------
# Tool loading helpers
# ---------------------------------------------------------------------------

async def load_tools(session: ClientSession) -> list:
    """Fetch the tool list from the MCP server."""
    result = await session.list_tools()
    return result.tools   # list of mcp.types.Tool


def mcp_tools_for_decision(mcp_tools: list) -> list[dict]:
    """
    Convert MCP tool objects to the plain-dict format Decision expects:
        [{"name": ..., "description": ..., "inputSchema": {...}}, ...]
    """
    out = []
    for t in mcp_tools:
        out.append({
            "name":        t.name,
            "description": getattr(t, "description", "") or "",
            "inputSchema": (
                t.inputSchema.model_dump()
                if hasattr(t.inputSchema, "model_dump")
                else dict(t.inputSchema or {})
            ),
        })
    return out


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

def final_answer_from(history: list[dict]) -> str:
    """
    Extract the best final answer from the run history.
    """
    answers = [e["text"] for e in history if e.get("kind") == "answer" and e.get("text")]
    if answers:
        return answers[-1]

    # Fallback: last action descriptor
    actions = [e for e in history if e.get("kind") == "action"]
    if actions:
        return f"(Tool result) {actions[-1].get('result_descriptor', '')}"

    return "I was unable to produce an answer. Please try rephrasing your question."


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

async def run(query: str) -> str:
    """
    Run the agent6 loop for *query* and return the final answer string.
    """
    ensure_gateway()
    run_id = uuid.uuid4().hex[:8]
    history: list[dict] = []
    prior_goals: list[Goal] = []

    # Durable memory: classify the user's query so facts/preferences
    # in it survive into future runs.
    memory.remember(query, source="user_query", run_id=run_id)

    async with mcp_session() as session:
        mcp_tools = await load_tools(session)
        tools = mcp_tools_for_decision(mcp_tools)

        for it in range(1, MAX_ITERATIONS + 1):
            print(f"─── iter {it} ───", flush=True)

            # ── 1. Memory read ──────────────────────────────────────────
            hits = memory.read(query, history)
            print(f"[memory.read]   {len(hits)} hits", flush=True)
            for hit in hits:
                if hit.kind in ("fact", "preference"):
                    print(f"                {hit.kind}: \"{hit.descriptor}\"", flush=True)

            # ── 2. Perception ───────────────────────────────────────────
            obs = perception.observe(query, hits, history, prior_goals, run_id)
            prior_goals = obs.goals

            if obs.all_done:
                for idx, g in enumerate(obs.goals):
                    prefix = "[perception]    " if idx == 0 else "                "
                    print(f"{prefix}[done] {g.text}", flush=True)
                print(f"\n[done] all {len(obs.goals)} goals satisfied\n", flush=True)
                break

            goal = obs.next_unfinished()
            
            # Print goals formatted exactly per specification
            for idx, g in enumerate(obs.goals):
                if g.done:
                    status = "done"
                elif goal and g.id == goal.id:
                    status = "progress"
                else:
                    status = "open"
                prefix = "[perception]    " if idx == 0 else "                "
                print(f"{prefix}[{status}] {g.text}", flush=True)
                if not g.done and g.attach_artifact_id:
                    print(f"                  attach={g.attach_artifact_id}", flush=True)

            # ── 3. Artifact attachment ──────────────────────────────────
            attached = []
            if goal.attach_artifact_id and artifacts.exists(goal.attach_artifact_id):
                art_bytes = artifacts.get_bytes(goal.attach_artifact_id)
                attached.append((goal.attach_artifact_id, art_bytes))
                print(f"[attach]        {goal.attach_artifact_id} ({len(art_bytes)} bytes)", flush=True)

            # ── 4. Decision ─────────────────────────────────────────────
            out = decision.next_step(goal, hits, attached, history, tools)

            # ── 5a. Answer path ─────────────────────────────────────────
            if out.is_answer:
                ans_preview = out.answer.replace('\n', ' ')
                if len(ans_preview) > 60:
                    ans_preview = ans_preview[:57] + "..."
                print(f"[decision]      ANSWER: {ans_preview}", flush=True)
                print("", flush=True) # Blank line separating iterations
                history.append({
                    "iter":    it,
                    "kind":    "answer",
                    "goal_id": goal.id,
                    "text":    out.answer,
                })
                continue

            # ── 5b. Tool path ───────────────────────────────────────────
            import json
            args_str = json.dumps(out.tool_call.arguments)
            print(f"[decision]      TOOL_CALL: {out.tool_call.name}({args_str})", flush=True)
            
            result_text, art_id = await action.execute(session, out.tool_call)
            if art_id:
                art_bytes = artifacts.get_bytes(art_id)
                size = len(art_bytes)
                clean_preview = result_text.split(" → ", 1)[1] if " → " in result_text else result_text
                if clean_preview.startswith(f"[artifact {art_id}]"):
                    clean_preview = clean_preview[len(f"[artifact {art_id}]"):].strip()
                print(f"[action]        → [artifact {art_id}, {size} bytes] preview: {clean_preview[:60].replace('\n', ' ')}...", flush=True)
            else:
                clean_action = result_text.split(" → ", 1)[1] if " → " in result_text else result_text
                print(f"[action]        → {clean_action.strip()}", flush=True)
            print("", flush=True) # Blank line separating iterations

            memory.record_outcome(
                tool_call=out.tool_call,
                result_text=result_text,
                artifact_id=art_id,
                run_id=run_id,
                goal_id=goal.id,
            )
            history.append({
                "iter":              it,
                "kind":              "action",
                "goal_id":           goal.id,
                "tool":              out.tool_call.name,
                "arguments":         out.tool_call.arguments,
                "result_descriptor": result_text[:300],
                "artifact_id":       art_id,
            })

    answer = final_answer_from(history)
    print(f"FINAL: {answer}\n", flush=True)
    return answer


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py \"your question here\"")
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    asyncio.run(run(query))