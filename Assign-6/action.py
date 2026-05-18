"""
action.py — Action role for the agent6 loop.

Action is pure dispatch — no LLM calls. It:
  1. Calls the named MCP tool via the live ClientSession.
  2. Serialises the result to a UTF-8 string.
  3. If the result exceeds ARTIFACT_THRESHOLD bytes, pushes the full
     payload to the artifact store and returns a short descriptor +
     the artifact id so Perception can attach it to future goals.
  4. If the result is small, returns the full text as the descriptor
     and None as the artifact id.

Return type: tuple[str, str | None]
  - str       : short descriptor (≤ 300 chars) embedded in history
  - str | None: artifact id ("art:...") if a blob was stored, else None

The threshold is intentionally conservative (4 KB) so that tool results
that fit in an LLM context window are never offloaded unnecessarily.
"""

from __future__ import annotations

import json
from typing import Any

from mcp import ClientSession

from artifacts import artifacts
from schemas import ToolCall

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Results larger than this are pushed to the artifact store
ARTIFACT_THRESHOLD_BYTES = 4 * 1024   # 4 KB


# ---------------------------------------------------------------------------
# Result serialisation helpers
# ---------------------------------------------------------------------------

def _to_text(result: Any) -> str:
    """
    Convert an MCP tool result to a plain UTF-8 string.

    MCP tool results come back as a list of content blocks.  We handle the
    three most common shapes:
      - list of {"type": "text", "text": "..."}   → concatenate texts
      - a plain string                              → use as-is
      - anything else                               → JSON-encode
    """
    if isinstance(result, str):
        return result

    if isinstance(result, list):
        parts = []
        for block in result:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                else:
                    parts.append(json.dumps(block, default=str))
            else:
                parts.append(str(block))
        return "\n".join(parts)

    # Fallback: JSON-encode whatever came back
    return json.dumps(result, indent=2, default=str)


def _short_descriptor(tool_name: str, args: dict, text: str, art_id: str | None) -> str:
    """Build a ≤ 300-char descriptor for the history dict."""
    args_str = ", ".join(f"{k}={repr(v)[:40]}" for k, v in list(args.items())[:3])
    prefix = f"{tool_name}({args_str})"
    if art_id:
        return f"{prefix} → [artifact {art_id}] {text[:100].strip()}"
    return f"{prefix} → {text[:200].strip()}"


# ---------------------------------------------------------------------------
# Action.execute
# ---------------------------------------------------------------------------

class Action:
    """
    Action role.

    Call execute() with the live MCP ClientSession and a ToolCall.
    Returns (descriptor, artifact_id | None).
    """

    async def execute(
        self,
        session: ClientSession,
        tool_call: ToolCall,
    ) -> tuple[str, str | None]:
        """
        Dispatch *tool_call* via *session* and handle the result.

        Steps
        -----
        1. Call session.call_tool(name, arguments).
        2. Serialise the result content to a UTF-8 string.
        3. If len(text) > ARTIFACT_THRESHOLD_BYTES, store in artifact store.
        4. Return (descriptor, artifact_id | None).

        Exceptions from the MCP call are caught and returned as an error
        descriptor so the loop can continue rather than crashing.
        """
        try:
            mcp_result = await session.call_tool(
                tool_call.name,
                tool_call.arguments,
            )
            # mcp_result.content is the list of content blocks
            raw_content = getattr(mcp_result, "content", mcp_result)
            result_text = _to_text(raw_content)
        except Exception as exc:
            error_text = f"Tool call failed: {tool_call.name} → {exc}"
            return error_text[:300], None

        # ── Artifact offload decision ─────────────────────────────────
        blob = result_text.encode("utf-8")
        art_id: str | None = None

        if len(blob) > ARTIFACT_THRESHOLD_BYTES:
            art_id = artifacts.put(
                blob,
                content_type="text/plain; charset=utf-8",
                source=tool_call.name,
                descriptor=f"Result of {tool_call.name}({list(tool_call.arguments.keys())})",
            )

        descriptor = _short_descriptor(tool_call.name, tool_call.arguments, result_text, art_id)
        return descriptor[:300], art_id


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

action = Action()
