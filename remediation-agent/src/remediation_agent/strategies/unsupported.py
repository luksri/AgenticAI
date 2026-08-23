"""The clean fallback for any category with no registered strategy.

Touches nothing in the workspace -- returning this instead of raising is what
makes an unrecognized `finding["category"]` (future SAST/secrets/IaC/etc.)
degrade to a structured result rather than crash the run.
"""
from __future__ import annotations

from typing import Any

from .base import StrategyContext


class UnsupportedStrategy:
    category = "unsupported"

    def remediate(self, ctx: StrategyContext) -> dict[str, Any]:
        return {
            "supported": False,
            "changed_files": [],
            "old_version": None,
            "new_version": None,
            "message": f"category {ctx.unit['category']!r} not yet supported",
        }
