"""
schemas.py — Typed boundary contracts for the agent6 roles.

Every role consumes and produces instances of these models.
The boundaries are checked at every transition.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: Literal["fact", "preference", "tool_outcome", "scratchpad"]
    keywords: list[str]
    descriptor: str            # one short human-readable line
    value: dict                # structured payload
    artifact_id: str | None = None   # handle into the artifact store
    source: str
    run_id: str
    goal_id: str | None = None
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Artifact store metadata (not the bytes themselves)
# ---------------------------------------------------------------------------

class Artifact(BaseModel):
    id: str                    # "art:<sha256-prefix>"
    content_type: str
    size_bytes: int
    source: str
    descriptor: str


# ---------------------------------------------------------------------------
# Goal — a single bounded imperative statement
# ---------------------------------------------------------------------------

class Goal(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    text: str                  # short imperative description
    done: bool = False
    attach_artifact_id: str | None = None


# ---------------------------------------------------------------------------
# Observation — what Perception returns to the loop
# ---------------------------------------------------------------------------

class Observation(BaseModel):
    goals: list[Goal]

    @property
    def all_done(self) -> bool:
        """True when every goal in the list is marked done."""
        return bool(self.goals) and all(g.done for g in self.goals)

    def next_unfinished(self) -> Goal | None:
        """Return the first goal that is not yet done, or None."""
        for g in self.goals:
            if not g.done:
                return g
        return None


# ---------------------------------------------------------------------------
# Tool call — a single MCP dispatch
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Decision output — either a plain-text answer OR a tool call (never both)
# ---------------------------------------------------------------------------

class DecisionOutput(BaseModel):
    answer: str | None = None      # populated when Decision can answer directly
    tool_call: ToolCall | None = None  # populated when Decision needs a tool

    @property
    def is_answer(self) -> bool:
        """True when this output is a direct answer (no tool needed)."""
        return self.answer is not None

    def model_post_init(self, __context) -> None:  # noqa: ANN001
        """Validate that exactly one field is populated."""
        if self.answer is None and self.tool_call is None:
            raise ValueError("DecisionOutput must have either answer or tool_call")
        if self.answer is not None and self.tool_call is not None:
            raise ValueError("DecisionOutput cannot have both answer and tool_call")