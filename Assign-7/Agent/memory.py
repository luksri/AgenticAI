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

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import re
import uuid
from typing import Literal

from llm_gatewayV7.client import LLM
from schemas import MemoryItem, ToolCall
from vector_index import VectorIndex

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_STATE_FILE = Path(__file__).parent / "sandbox" / "state" / "memory.json"
_EMBEDDABLE_KINDS = {"fact", "preference", "tool_outcome"}

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


def _index() -> VectorIndex:
    idx = VectorIndex(_STATE_FILE.parent)
    if idx.size == 0:
        for item in _load():
            if item.embedding is not None:
                idx.add(item.id, item.embedding)
        if idx.size > 0:
            idx.persist()
    return idx


def _try_embed(text: str, task_type: str) -> list[float] | None:
    try:
        resp = LLM().embed(text, task_type=task_type)
        return list(resp["embedding"])
    except Exception as e:
        import sys
        print(f"[memory] embedding failed ({e!r}); item written/processed without vector", file=sys.stderr)
        return None


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
def _vector_search(
    query: str,
    *,
    kinds: list[str] | None,
    top_k: int,
) -> list[MemoryItem]:
    qvec = _try_embed(query, task_type="retrieval_query")
    if qvec is None:
        return []
    idx = _index()
    if idx.size == 0:
        return []
    hits = idx.search(qvec, k=top_k * 2 if kinds else top_k)
    if not hits:
        return []
    by_id: dict[str, MemoryItem] = {item.id: item for item in _load()}
    out: list[MemoryItem] = []
    for item_id, _score in hits:
        item = by_id.get(item_id)
        if item is None:
            continue
        if kinds and item.kind not in kinds:
            continue
        out.append(item)
        if len(out) >= top_k:
            break
    return out


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Module-level write helper (not a MemoryService method)
# ---------------------------------------------------------------------------

def _persist_item(item: MemoryItem) -> MemoryItem:
    """Append `item` to the JSON store and, if it has an embedding, to the
    FAISS index. Returns the same item for caller convenience."""
    items = _load()
    items.append(item)
    _save(items)
    if item.embedding is not None and item.kind in _EMBEDDABLE_KINDS:
        idx = _index()
        idx.add(item.id, item.embedding)
        idx.persist()
    return item


class MemoryService:
    """
    The memory service consumed by the agent loop and other roles.

    All methods are synchronous; reads are pure Python; only remember() hits
    the LLM gateway.
    """

    # ------------------------------------------------------------------
    # Read — vector first, fallback to keyword overlap (defined earlier as
    # standalone functions; MemoryService.read delegates to them)
    # ------------------------------------------------------------------

    def read(
        self,
        query: str,
        history: list[dict] | None = None,
        kinds: list[str] | None = None,
        top_k: int = 8,
    ) -> list[MemoryItem]:
        """
        Reads first run a vector search through FAISS over the items that carry
        embeddings. When the vector path returns at least one hit, those items
        are returned. Otherwise falls back to keyword overlap.
        """
        vec_hits = _vector_search(query, kinds=kinds, top_k=top_k)
        if vec_hits:
            return vec_hits

        items = _load()
        query_tokens = _tokenize(query)

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
            import sys
            print(f"[memory] remember() skipped — gateway unavailable: {exc}", file=sys.stderr)
            return None

        kind = extracted["kind"]
        embedding = None
        if kind in _EMBEDDABLE_KINDS:
            embedding = _try_embed(extracted["descriptor"], task_type="retrieval_document")

        item = MemoryItem(
            id=uuid.uuid4().hex,
            kind=kind,
            keywords=[kw.lower() for kw in extracted.get("keywords", [])],
            descriptor=extracted["descriptor"],
            value=extracted.get("value", {}),
            artifact_id=None,
            embedding=embedding,
            source=source,
            run_id=run_id,
            goal_id=goal_id,
            confidence=float(extracted.get("confidence", 1.0)),
        )

        return _persist_item(item)

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

        embedding = _try_embed(descriptor, task_type="retrieval_document")

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
            embedding=embedding,
            source="action",
            run_id=run_id,
            goal_id=goal_id,
            confidence=1.0,
        )

        return _persist_item(item)

    def add_fact(
        self,
        descriptor: str,
        *,
        value: dict | None = None,
        keywords: list[str] | None = None,
        source: str,
        run_id: str,
        goal_id: str | None = None,
    ) -> MemoryItem:
        """Direct fact write used by document-indexing tools. Skips the LLM
        classifier (kind is known) but still embeds the descriptor."""
        embedding = _try_embed(descriptor, task_type="retrieval_document")
        item = MemoryItem(
            id=uuid.uuid4().hex,
            kind="fact",
            keywords=list({k.lower() for k in (keywords or list(_tokenize(descriptor))[:10])}),
            descriptor=descriptor,
            value=value or {},
            embedding=embedding,
            source=source,
            run_id=run_id,
            goal_id=goal_id,
        )
        return _persist_item(item)

    def clear(self) -> None:
        """Wipe persistent memory and the vector index."""
        if _STATE_FILE.exists():
            _STATE_FILE.unlink()
        VectorIndex(_STATE_FILE.parent).clear()


# ---------------------------------------------------------------------------
# Module-level singleton — imported by other roles
# ---------------------------------------------------------------------------

memory = MemoryService()
