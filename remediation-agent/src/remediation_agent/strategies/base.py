"""The `RemediationStrategy` contract, keyed by `finding["category"]`.

A strategy turns a `RemediationUnit` (findings already grouped and located)
into a concrete edit, or a clean "not supported" result. Only `"SCA"` is
implemented for now (`sca.py`); every other category falls back to
`unsupported.py` via `strategies.registry.get`, never raising.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from s17code.coding.edit import EditLedger
from s17code.coding.workspace import Workspace

from remediation_agent.ecosystems.base import EcosystemAdapter
from remediation_agent.schemas.state import RemediationUnit


@dataclass
class StrategyContext:
    """Everything one strategy invocation needs for one remediation unit."""

    workspace: Workspace
    ledger: EditLedger
    adapter: EcosystemAdapter
    unit: RemediationUnit
    locations: list[dict[str, Any]]
    # Set by `generate_fix.py` from `state["validation_feedback"]` on a retry
    # pass (a downstream gate rejected the previous attempt and explained
    # why); None on a first attempt. Only `SASTStrategy`'s LLM-fallback tier
    # reads this -- a deterministic template has nothing to do with feedback,
    # since it produces the same output regardless.
    feedback: str | None = None


class RemediationStrategy(Protocol):
    """One category's worth of remediation know-how.

    `remediate` returns a FixResult-shaped dict:
    ``{"supported": bool, "changed_files": list[str], "old_version": str | None,
    "new_version": str | None, "message": str}`` (SAST strategies also set
    ``"fix_tier": "template" | "llm"``). Exceptions from the underlying
    adapter (`EditError`, `GuardError`, `FixNotFoundError`) or an LLM-fix path
    (`LLMFixError`) are allowed to propagate -- converting them into a
    `decision` is the calling graph node's job, not the strategy's.

    May be declared `def` (e.g. `SCAStrategy`, purely deterministic) or
    `async def` (e.g. `SASTStrategy`, which needs to `await` a chat-model
    call). `graph/nodes/unit/generate_fix.py` calls `strategy.remediate(ctx)`
    and awaits the result only if it's awaitable, so either form works
    without the graph needing to know which. A strategy must never bridge
    its own async work onto a fresh event loop/thread to fake a sync
    signature -- that would block the shared event loop every other
    concurrently-running unit and job depend on.
    """

    category: str

    def remediate(self, ctx: StrategyContext) -> dict[str, Any]: ...
