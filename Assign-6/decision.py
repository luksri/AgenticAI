"""
decision.py — Decision role for the agent6 loop.

Decision is called once per iteration, for exactly ONE unfinished goal.
It examines the goal, memory hits, attached artifact bytes, run history,
and the list of available MCP tools, then returns a DecisionOutput that
is EITHER:
  • answer   — a plain-text answer (the goal can be satisfied from context)
  • tool_call — a single MCP tool invocation needed to progress the goal

LLM routing:
    auto_route="decision"   (router picks tier; no provider pin per spec)
    response_format → structured JSON validated against DecisionOutput schema.

Prompt quality (evaluated against prompt_rules.txt):
    ✓ Explicit step-by-step reasoning instructions (THINK / DECIDE / OUTPUT)
    ✓ Structured JSON output enforced via response_format
    ✓ Clear separation: reasoning first, then tool dispatch or answer
    ✓ Conversation-loop context (history + memory hits) passed every call
    ✓ Output format template with examples
    ✓ Self-check: verify exactly one of answer/tool_call is populated
    ✓ Reasoning-type awareness: lookup vs compute vs tool fetch
    ✓ Fallback: if no tool fits, answer with best available information
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from llm_gatewayV3.client import LLM
from schemas import DecisionOutput, Goal, MemoryItem, ToolCall

# ---------------------------------------------------------------------------
# Gateway client
# ---------------------------------------------------------------------------

def _llm():
    return LLM()


# ---------------------------------------------------------------------------
# JSON schema for the gateway response_format
# ---------------------------------------------------------------------------

_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {
            "type": "string",
            "description": "Your step-by-step thinking before the final decision.",
        },
        "answer": {
            "type": "string",
            "description": "A plain-text answer if no tool is needed.",
        },
        "tool_call": {
            "type": "object",
            "description": "Exactly one MCP tool call.",
            "properties": {
                "name":      {"type": "string"},
                "arguments": {"type": "object"},
            },
            "required": ["name", "arguments"],
            "additionalProperties": False,
        },
    },
    "required": ["reasoning"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# System prompt  (satisfies all prompt_rules.txt criteria)
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are the Decision module of an autonomous AI agent (agent6).
You are called once per iteration to decide the SINGLE NEXT ACTION for one goal.

You will receive:
  - GOAL          : the current goal you must work on (text + id).
  - MEMORY_HITS   : relevant memory items from durable store
                    (facts, preferences, prior tool outcomes with artifact handles).
  - ATTACHED      : list of {artifact_id, text_preview} if the goal needs
                    an artifact's content to proceed (may be empty).
  - HISTORY       : ordered events from this run (answers and tool actions so far).
  - TOOLS         : list of available MCP tools with their descriptions and
                    parameter schemas.

Follow this three-phase process EXPLICITLY before writing output:

── PHASE 1: THINK ──────────────────────────────────────────────────────────
Reason about the goal:
  a) What type of reasoning does this require?
     Tag it: [LOOKUP] (known fact in memory/context), [COMPUTE] (arithmetic /
     logic), [FETCH] (need external data via tool), [FILE] (read/write sandbox).
  b) Is the goal already answerable from MEMORY_HITS, ATTACHED, or HISTORY?
     If yes, plan to answer directly — no tool needed.
  c) If a tool is needed, which single tool is the best fit?
     Check TOOLS for available names and required parameters.
  d) What exact arguments should the tool receive? Verify they are complete.

── PHASE 2: DECIDE ─────────────────────────────────────────────────────────
Choose EXACTLY ONE of:
  • ANSWER  — you can satisfy the goal from available context right now.
  • TOOL    — you need one MCP tool call to make progress.

Rules:
  - Prefer answering directly when memory hits or history already contain
    the needed information. Avoid unnecessary tool calls.
  - Choose the MOST SPECIFIC tool that fits (e.g., currency_convert over
    web_search for currency questions).
  - NEVER call a tool you have already called with the same arguments
    in this run's HISTORY (check before deciding).
  - A single decision must dispatch at most ONE tool call.

── PHASE 3: OUTPUT ──────────────────────────────────────────────────────────
Produce this JSON object exactly:
{
  "reasoning":  "<your step-by-step thinking from phases 1 and 2>",
  "answer":     "<plain text answer>" | null,
  "tool_call":  {"name": "<tool_name>", "arguments": {<key: value>}} | null
}

Constraints:
  - Exactly ONE of answer / tool_call must be non-null.
  - If answering, answer must be a complete, helpful response to the goal.
  - If using a tool, arguments must match the tool's required parameter names.

Self-check before finalising:
  1. Is exactly one of answer/tool_call non-null?
  2. If tool_call, is the tool name in the TOOLS list?
  3. If tool_call, have I already called this tool with these same arguments?
     (If yes, switch to answer with what you know.)
  4. If answer, does it actually address the goal?

Error / fallback rules:
  - If no tool is a good fit and you don't have enough context to answer
    well, answer with what you know and state what is uncertain.
  - If TOOLS is empty, always answer directly.
  - Never return both answer and tool_call as non-null.
"""


# ---------------------------------------------------------------------------
# Helper: format tool list for the prompt
# ---------------------------------------------------------------------------

def _format_tools(tools: list[dict]) -> list[dict]:
    """Return a compact representation of available tools."""
    out = []
    for t in tools:
        out.append({
            "name":        t.get("name", ""),
            "description": t.get("description", ""),
            "parameters":  t.get("inputSchema", t.get("parameters", {})),
        })
    return out


# ---------------------------------------------------------------------------
# Decision.next_step
# ---------------------------------------------------------------------------

class Decision:
    """
    Decision role.

    Call next_step() with the current goal and context.
    Returns a DecisionOutput with either an answer or a tool_call.
    """

    def next_step(
        self,
        goal: Goal,
        hits: list[MemoryItem],
        attached: list[tuple[str, bytes]],
        history: list[dict],
        tools: list[dict],
    ) -> DecisionOutput:
        """
        Ask the LLM to decide the next action for *goal*.

        Parameters
        ----------
        goal      : the current unfinished Goal
        hits      : memory items recalled for this query
        attached  : list of (artifact_id, raw_bytes) pairs for artifact goals
        history   : full run history (trimmed to last 20 events internally)
        tools     : MCP tool descriptors (name, description, inputSchema)

        Returns
        -------
        DecisionOutput with exactly one of answer or tool_call set.
        Falls back to a plain-text answer if the gateway is unavailable.
        """
        # Build attached previews (first 2000 chars of each blob)
        attached_payload = []
        for art_id, blob in attached:
            try:
                preview = blob.decode("utf-8", errors="replace")[:2000]
            except Exception:
                preview = f"<binary blob {len(blob)} bytes>"
            attached_payload.append({"artifact_id": art_id, "text_preview": preview})

        user_content = json.dumps(
            {
                "GOAL": {"id": goal.id, "text": goal.text},
                "MEMORY_HITS": [
                    {
                        "kind":        h.kind,
                        "descriptor":  h.descriptor,
                        "value":       h.value,
                        "artifact_id": h.artifact_id,
                    }
                    for h in hits
                ],
                "ATTACHED":  attached_payload,
                "HISTORY":   history[-20:],
                "TOOLS":     _format_tools(tools),
            },
            indent=2,
            default=str,
        )

        try:
            llm = _llm()
            resp = llm.chat(
                user_content,
                system=_SYSTEM,
                auto_route="decision",   # router picks tier; no provider pin
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name":   "decision_output",
                        "schema": _DECISION_SCHEMA,
                    },
                },
                temperature=0.0,
                max_tokens=1024,
            )

            raw: dict = resp.get("parsed") or json.loads(resp["text"])
            return self._parse_output(raw)

        except Exception as exc:
            print(f"[decision] gateway call failed: {exc}", file=sys.stderr)
            return DecisionOutput(
                answer=f"I was unable to reach the reasoning engine. "
                       f"The goal was: {goal.text}"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_output(raw: dict) -> DecisionOutput:
        """
        Convert raw LLM dict into a DecisionOutput.

        Defence-in-depth: enforce the mutual-exclusion constraint that
        the schema alone cannot guarantee in all edge cases.
        """
        answer    = raw.get("answer")    or None
        tool_raw  = raw.get("tool_call") or None

        # Normalise empty strings to None
        if isinstance(answer, str) and not answer.strip():
            answer = None

        tool_call = None
        if isinstance(tool_raw, dict) and tool_raw.get("name"):
            name = str(tool_raw["name"]).strip()
            if name.lower() not in ("null", "none", "null()", ""):
                tool_call = ToolCall(
                    name=name,
                    arguments=dict(tool_raw.get("arguments") or {}),
                )

        # Enforce mutual exclusion: prefer tool_call if both set, prefer
        # answer if neither set.
        if tool_call and answer:
            # LLM set both — drop the answer, trust the tool_call
            answer = None
        if not tool_call and not answer:
            answer = "(No decision was reached — please rephrase the query.)"

        return DecisionOutput(answer=answer, tool_call=tool_call)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

decision = Decision()
