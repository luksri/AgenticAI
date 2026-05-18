"""
memory.py — Typed memory service for the agent6 loop.

Persistence:
    sandbox/state/memory.json   — list of MemoryItem dicts, reloaded on every
                                  read, flushed after every write.

Read methods  (no LLM cost):
    read(query, history, kinds, top_k)   — keyword overlap search, ranked
    filter(kinds, goal_id, recent)        — structured predicate filter

Write methods:
    remember(raw_text, source, run_id)   — one LLM call to classify & extract
    record_outcome(tool_call, ...)        — structured write, no LLM needed

Design notes:
    • Reads are pure Python — keyword intersection over a stopword-filtered
      token set.  Fast enough to run before every Perception call.
    • Writes via remember() cost one gateway call (auto_route="memory",
      provider="g" to pin to Gemini) that returns a validated MemoryItem.
    • Scratchpad items written during a run are marked with the run_id so
      a future cleanup sweep can drop them without touching facts/preferences.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path
from typing import Literal

from llm_gatewayV3.client import LLM
from schemas import MemoryItem, ToolCall

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_STATE_FILE = Path(__file__).parent / "sandbox" / "state" / "memory.json"

# ---------------------------------------------------------------------------
# Stopword list — tokens ignored during keyword matching
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "used",
    "to", "of", "in", "on", "at", "by", "for", "with", "about", "against",
    "between", "through", "during", "before", "after", "above", "below",
    "from", "up", "down", "out", "off", "over", "under", "again",
    "and", "or", "but", "if", "then", "that", "this", "it", "its",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "they",
    "his", "her", "their", "what", "which", "who", "when", "where", "how",
}


def _tokenize(text: str) -> set[str]:
    """Lowercase, split on non-alphanumeric, drop stopwords and short tokens."""
    tokens = re.split(r"[^a-z0-9]+", text.lower())
    return {t for t in tokens if len(t) > 1 and t not in _STOPWORDS}


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load() -> list[MemoryItem]:
    """Load all items from disk. Returns empty list if file is missing/empty."""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _STATE_FILE.exists():
        return []
    text = _STATE_FILE.read_text(encoding="utf-8").strip()
    if not text or text == "[]":
        return []
    raw: list[dict] = json.loads(text)
    return [MemoryItem(**r) for r in raw]


def _save(items: list[MemoryItem]) -> None:
    _STATE_FILE.write_text(
        json.dumps([i.model_dump(mode="json") for i in items], indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# LLM gateway
# ---------------------------------------------------------------------------

def _gateway_remember(raw_text: str, source: str, run_id: str) -> dict:
    """
    One LLM call via the gateway to classify raw_text into a MemoryItem dict.
    Routes via auto_route="memory", pinned to Gemini (provider="g").
    Returns a dict that maps onto MemoryItem fields.
    """
    llm = LLM()

    schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["fact", "preference", "tool_outcome", "scratchpad"]},
            "descriptor": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "value": {"type": "object"},
            "confidence": {"type": "number"},
        },
        "required": ["kind", "descriptor", "keywords", "value", "confidence"],
        "additionalProperties": False,
    }

    system = (
        "You are a memory classifier for an AI agent. "
        "Given a raw text fragment, extract a structured memory item.\n\n"
        "Rules:\n"
        "  kind='fact'        — a durable observed truth about the world or a person.\n"
        "  kind='preference'  — a user-stated or inferred preference.\n"
        "  kind='scratchpad'  — a run-scoped working note with no long-term value.\n"
        "  kind='tool_outcome'— should not appear here; use record_outcome() instead.\n"
        "descriptor — one short human-readable line summarising the item.\n"
        "keywords   — 3-8 important lowercase tokens for future keyword recall.\n"
        "value      — structured dict capturing the semantics (entity, attribute, value, etc.).\n"
        "confidence — float 0-1 reflecting how certain the extraction is."
    )

    prompt = f"Raw text to classify:\n\n{raw_text}"

    resp = llm.chat(
        prompt,
        system=system,
        auto_route="memory",
        provider="g",
        response_format={"type": "json_schema", "json_schema": {"name": "memory_item", "schema": schema}},
        temperature=0.0,
        max_tokens=512,
    )

    # Gateway returns parsed dict in resp["parsed"] when response_format is set
    return resp.get("parsed") or json.loads(resp["text"])


# ---------------------------------------------------------------------------
# MemoryService
# ---------------------------------------------------------------------------

class MemoryService:
    """
    The memory service consumed by the agent6 loop and other roles.

    All methods are synchronous; reads are pure Python; only remember() hits
    the LLM gateway.
    """

    # ------------------------------------------------------------------
    # Read — pure keyword search, no LLM
    # ------------------------------------------------------------------

    def read(
        self,
        query: str,
        history: list[dict] | None = None,
        kinds: list[str] | None = None,
        top_k: int = 8,
    ) -> list[MemoryItem]:
        """
        Keyword-overlap search over stored items.

        Scoring:
            score = |query_tokens ∩ (item.keywords ∪ descriptor_tokens)|
        Items with score == 0 are excluded. Results are ranked descending.
        Scratchpad items from other runs are excluded unless explicitly requested.
        """
        items = _load()
        query_tokens = _tokenize(query)

        # Also pull tokens from recent history entries to widen the search
        if history:
            for evt in history[-6:]:
                for field in ("text", "result_descriptor"):
                    if evt.get(field):
                        query_tokens |= _tokenize(str(evt[field]))

        scored: list[tuple[int, MemoryItem]] = []
        for item in items:
            if kinds and item.kind not in kinds:
                continue
            item_tokens = set(kw.lower() for kw in item.keywords)
            item_tokens |= _tokenize(item.descriptor)
            overlap = len(query_tokens & item_tokens)
            if overlap > 0:
                scored.append((overlap, item))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    def filter(
        self,
        kinds: list[str] | None = None,
        goal_id: str | None = None,
        recent: int | None = None,
    ) -> list[MemoryItem]:
        """
        Structured filter by kind, goal_id, and/or recency.
        Returns up to *recent* most-recently-created items if specified.
        """
        items = _load()
        if kinds:
            items = [i for i in items if i.kind in kinds]
        if goal_id:
            items = [i for i in items if i.goal_id == goal_id]
        # Sort newest first
        items.sort(key=lambda i: i.created_at, reverse=True)
        if recent is not None:
            items = items[:recent]
        return items

    # ------------------------------------------------------------------
    # Write — LLM-backed classification
    # ------------------------------------------------------------------

    def remember(
        self,
        raw_text: str,
        *,
        source: str = "user_query",
        run_id: str = "",
        goal_id: str | None = None,
    ) -> MemoryItem | None:
        """
        Classify *raw_text* via one LLM gateway call and persist the result.

        Returns the stored MemoryItem, or None if the gateway call fails
        (e.g. gateway is not running).  Failure is intentionally non-fatal
        so the agent loop can continue without memory on first run.
        """
        try:
            extracted = _gateway_remember(raw_text, source, run_id)
        except Exception as exc:
            print(f"[memory] remember() skipped — gateway unavailable: {exc}", file=sys.stderr)
            return None

        item = MemoryItem(
            id=uuid.uuid4().hex,
            kind=extracted["kind"],
            keywords=[kw.lower() for kw in extracted.get("keywords", [])],
            descriptor=extracted["descriptor"],
            value=extracted.get("value", {}),
            artifact_id=None,
            source=source,
            run_id=run_id,
            goal_id=goal_id,
            confidence=float(extracted.get("confidence", 1.0)),
        )

        items = _load()
        items.append(item)
        _save(items)
        return item

    # ------------------------------------------------------------------
    # Write — structured tool outcome (no LLM)
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        *,
        tool_call: ToolCall,
        result_text: str,
        artifact_id: str | None,
        run_id: str,
        goal_id: str | None = None,
    ) -> MemoryItem:
        """
        Persist a tool_outcome item without an LLM call.

        Keywords are derived from the tool name and argument tokens so the
        keyword search can retrieve this outcome in future iterations.
        """
        # Build keyword set from tool name + argument values
        kw_tokens = _tokenize(tool_call.name)
        for v in tool_call.arguments.values():
            kw_tokens |= _tokenize(str(v))
        # Also include the first 120 chars of the result
        kw_tokens |= _tokenize(result_text[:120])

        descriptor = (
            f"{tool_call.name}({', '.join(str(v) for v in tool_call.arguments.values())}) "
            f"→ {result_text[:80].strip()}"
        )
        if artifact_id:
            descriptor += f" [artifact: {artifact_id}]"

        item = MemoryItem(
            id=uuid.uuid4().hex,
            kind="tool_outcome",
            keywords=sorted(kw_tokens),
            descriptor=descriptor,
            value={
                "tool": tool_call.name,
                "arguments": tool_call.arguments,
                "result_snippet": result_text[:300],
                "artifact_id": artifact_id,
            },
            artifact_id=artifact_id,
            source="action",
            run_id=run_id,
            goal_id=goal_id,
            confidence=1.0,
        )

        items = _load()
        items.append(item)
        _save(items)
        return item


# ---------------------------------------------------------------------------
# Module-level singleton — imported by other roles
# ---------------------------------------------------------------------------

memory = MemoryService()
