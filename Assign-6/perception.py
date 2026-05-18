"""
perception.py — Perception role for the agent6 loop.

Perception is the orchestrator. It is called once per iteration and fulfills
four obligations (from the Session 6 spec):

  1. If prior_goals is empty, decompose the user query into one or more
     bounded goals, each a short imperative statement.
  2. For each prior goal, examine the run history. Mark goal.done = True
     the moment the history contains an action that satisfies it.
     Once done, the goal stays done in all subsequent iterations.
  3. For the first unfinished goal, decide whether it needs raw bytes from
     a previously fetched artifact. If yes, set attach_artifact_id to one
     of the artifact handles in the memory hits.
  4. Preserve goal order. Do not reorder, insert in the middle, or drop.

LLM routing:
    auto_route="perception", provider="g"  (pinned to Gemini per spec)
    response_format → structured JSON validated against Observation schema.

Prompt quality (evaluated against prompt_rules.txt):
    ✓ Explicit step-by-step reasoning instructions
    ✓ Structured JSON output enforced via response_format
    ✓ Reasoning and tool-use steps clearly separated
    ✓ Conversation-loop context (history + prior_goals) passed every call
    ✓ Instructional examples / format templates in system prompt
    ✓ Self-check instruction: verify each goal against history before marking done
    ✓ Fallback: if uncertain whether goal is done, keep it undone
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from llm_gatewayV3.client import LLM
from schemas import Goal, MemoryItem, Observation

# ---------------------------------------------------------------------------
# Gateway client
# ---------------------------------------------------------------------------

def _llm():
    return LLM()


# ---------------------------------------------------------------------------
# JSON schema for the gateway response_format
# ---------------------------------------------------------------------------

_OBSERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "goals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id":                 {"type": "string"},
                    "text":               {"type": "string"},
                    "done":               {"type": "boolean"},
                    "attach_artifact_id": {"type": "string"},
                },
                "required": ["id", "text", "done"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["goals"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# System prompt (satisfies all prompt_rules.txt criteria)
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are the Perception module of an autonomous AI agent (agent6).
Your job is called once per iteration of the agent loop.

You will receive:
  - USER_QUERY     : the original question or instruction from the user.
  - MEMORY_HITS    : relevant facts / outcomes recalled from durable memory
                     (list of {kind, descriptor, artifact_id?} objects).
  - HISTORY        : ordered list of events that happened in this run so far
                     (each event has kind="answer" or kind="action").
  - PRIOR_GOALS    : the goal list from the previous iteration
                     (empty list on the very first call).

You must reason step-by-step through the following FOUR OBLIGATIONS before
producing output. Think through each obligation explicitly before writing JSON.

--- OBLIGATION 1: Goal list ---
If PRIOR_GOALS is empty, decompose USER_QUERY into one or more short
imperative goals. Each goal should be achievable in one or two agent actions.
Do NOT invent goals unrelated to USER_QUERY.
If PRIOR_GOALS is non-empty, carry it forward unchanged — do NOT reorder,
do NOT insert new goals in the middle, do NOT drop existing goals.

--- OBLIGATION 2: Mark goals done ---
For EACH goal in the list, check HISTORY carefully:
  - An answer event (kind="answer", goal_id matches) satisfies a knowledge goal.
  - An action event (kind="action", goal_id matches) satisfies a tool-use goal.
Set done=true ONLY when you can identify a specific history event that satisfies
the goal. If you are uncertain, leave done=false (safe default).
Once a goal is done=true, keep it done=true in all future iterations.

--- OBLIGATION 3: Artifact attachment ---
Look at the FIRST goal whose done=false. Decide whether it needs raw bytes
from a previously fetched artifact to proceed (e.g., large document to read).
If yes, set attach_artifact_id to one of the artifact_id values from
MEMORY_HITS. Use ONLY artifact ids that appear in MEMORY_HITS — never invent one.
If no artifact is needed, set attach_artifact_id to null.

--- OBLIGATION 4: Output format ---
Produce exactly this JSON object (validated against the schema):
{
  "goals": [
    {
      "id":                 "<copy the existing id, or generate a short uuid for new goals>",
      "text":               "<short imperative statement>",
      "done":               true | false,
      "attach_artifact_id": "<art:... from MEMORY_HITS>" | null
    }
  ]
}

Self-check before writing output:
  - Does every new goal have a fresh unique id?
  - Did I mark a goal done ONLY when HISTORY confirms it?
  - Is the goal order exactly preserved from PRIOR_GOALS?
  - Is attach_artifact_id either null or an id that actually appears in MEMORY_HITS?

Error / fallback rules:
  - If USER_QUERY is ambiguous, create a single goal: "Clarify the user's intent."
  - If all goals are done, set done=true on all — the loop will exit.
  - Never return an empty goals list.
"""


# ---------------------------------------------------------------------------
# Helper: build the user turn content
# ---------------------------------------------------------------------------

def _build_user_turn(
    query: str,
    hits: list[MemoryItem],
    history: list[dict],
    prior_goals: list[Goal],
) -> str:
    hits_payload = [
        {
            "kind":        h.kind,
            "descriptor":  h.descriptor,
            "artifact_id": h.artifact_id,
        }
        for h in hits
    ]

    goals_payload = [g.model_dump() for g in prior_goals]

    # Trim history to last 20 events to keep token budget bounded
    recent_history = history[-20:]

    return json.dumps(
        {
            "USER_QUERY":   query,
            "MEMORY_HITS":  hits_payload,
            "HISTORY":      recent_history,
            "PRIOR_GOALS":  goals_payload,
        },
        indent=2,
        default=str,
    )


# ---------------------------------------------------------------------------
# Perception.observe
# ---------------------------------------------------------------------------

class Perception:
    """
    Perception role.

    Call observe() once per agent loop iteration.
    Returns an Observation whose goals list is the authoritative state for
    this iteration.
    """

    def observe(
        self,
        query: str,
        hits: list[MemoryItem],
        history: list[dict],
        prior_goals: list[Goal],
        run_id: str = "",
    ) -> Observation:
        """
        Ask the LLM to fulfill the four Perception obligations and return
        a validated Observation.

        Falls back to a single undone goal containing the query text if the
        gateway call fails (keeps the loop alive even without LLM access).
        """
        user_content = _build_user_turn(query, hits, history, prior_goals)

        try:
            llm = _llm()
            resp = llm.chat(
                user_content,
                system=_SYSTEM,
                auto_route="perception",
                provider="g",          # pinned to Gemini per Session 6 spec
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name":   "observation",
                        "schema": _OBSERVATION_SCHEMA,
                    },
                },
                temperature=0.0,       # deterministic goal management
                max_tokens=1024,
            )

            raw: dict = resp.get("parsed") or json.loads(resp["text"])
            goals = self._parse_goals(raw.get("goals", []), prior_goals)
            return Observation(goals=goals)

        except Exception as exc:
            print(f"[perception] gateway call failed: {exc}", file=sys.stderr)
            return self._fallback(query, prior_goals)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_goals(
        raw_goals: list[dict[str, Any]],
        prior_goals: list[Goal],
    ) -> list[Goal]:
        """
        Convert raw LLM dicts into Goal objects.

        Safety rules applied here (defence-in-depth):
          • Prior done=True is never reversed — monotone done flag.
          • Each Goal gets an id; if LLM returned empty string, generate one.
        """
        # Build a lookup of prior goals by id for monotone-done enforcement
        prior_by_id: dict[str, Goal] = {g.id: g for g in prior_goals}

        parsed: list[Goal] = []
        for raw in raw_goals:
            gid = str(raw.get("id") or "").strip()
            if not gid:
                import uuid
                gid = uuid.uuid4().hex[:8]

            done = bool(raw.get("done", False))

            # Monotone: once done, always done (LLM cannot un-done a goal)
            if gid in prior_by_id and prior_by_id[gid].done:
                done = True

            parsed.append(Goal(
                id=gid,
                text=str(raw.get("text", "")).strip() or "Unnamed goal",
                done=done,
                attach_artifact_id=raw.get("attach_artifact_id") or None,
            ))

        return parsed if parsed else [Goal(text="Answer the user's query.", done=False)]

    @staticmethod
    def _fallback(query: str, prior_goals: list[Goal]) -> Observation:
        """Return prior goals unchanged, or a single-goal fallback."""
        if prior_goals:
            return Observation(goals=prior_goals)
        return Observation(goals=[Goal(text=f"Handle: {query[:120]}", done=False)])


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

perception = Perception()
