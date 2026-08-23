"""Per-unit subgraph, step 3: apply the category-specific remediation strategy."""
from __future__ import annotations

import inspect
import logging
from typing import Any

from s17code.coding.workspace import Workspace
from s17code.coding.edit import EditLedger

from remediation_agent.ecosystems.registry import get as get_adapter
from remediation_agent.strategies.base import StrategyContext
from remediation_agent.strategies.registry import get as get_strategy

logger = logging.getLogger(__name__)


async def generate_fix(state: dict) -> dict[str, Any]:
    workspace = Workspace.open(state["workspace_root"])
    adapter = get_adapter(state["ecosystem"])
    ctx = StrategyContext(
        workspace=workspace,
        ledger=EditLedger(),
        adapter=adapter,
        unit=state["unit"],
        locations=state["locations"],
        # None on a first attempt; set by validate_build_test.py/guard_check.py
        # (via _retry.py) when this call is a retry of an LLM-authored SAST
        # fix a downstream gate rejected -- see strategies/base.py.
        feedback=state.get("validation_feedback"),
    )
    strategy = get_strategy(state["unit"]["category"])

    try:
        # Most strategies (e.g. SCAStrategy) are plain synchronous callables,
        # since session-17's underlying edit/exec primitives are all sync.
        # SASTStrategy is `async def` (it awaits a chat-model call for its
        # LLM-fallback path), so `remediate(ctx)` returns a coroutine there
        # instead of a dict -- await it only in that case, rather than
        # requiring every strategy to declare the same signature.
        result = strategy.remediate(ctx)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        # Deliberately broad, not a specific exception tuple. Known failure
        # modes (s17code's EditError/GuardError, ecosystems.base's
        # FixNotFoundError, sast.llm_fix's LLMFixError for an unparseable
        # model response) all land here, but so does anything a strategy
        # can't itself predict -- an LLM API auth/rate-limit/network error
        # surfaced a real gap here: it isn't any of those four types, and a
        # narrower except let it propagate all the way out of `graph.ainvoke`
        # and abort the entire run instead of failing just this one unit.
        # "Never crash the run, always report a structured result" (this
        # project's core contract, stated in unit_subgraph.py) has to hold
        # for failures the strategy layer can't enumerate in advance, not
        # only the ones it knows the names of.
        #
        # A strategy may have partially written to disk before raising (e.g.
        # one finding in a multi-finding unit succeeded before a later one
        # failed) -- reset here for the same reason every other failing path
        # in this subgraph does: units for one repo share a single on-disk
        # checkout (serialized via execution/locks.py), so a stray dirty
        # write left behind would leak into whichever unit runs next.
        # Not retried, unlike guard_check.py/validate_build_test.py's own
        # failure paths: a failure here happens before `fix_result` (and
        # therefore `fix_tier`) exists, so there's no reliable way to tell
        # whether this came from the deterministic template tier (retrying
        # would just reproduce the identical failure and burn the retry
        # budget without the LLM tier ever getting a turn) or the LLM tier
        # (see _retry.py's docstring for the full reasoning).
        logger.exception("strategy.remediate raised for unit %s", state["unit"]["unit_id"])
        workspace.reset()
        return {"decision": "fix_failed", "error": f"{type(exc).__name__}: {exc}"}

    if not result.get("supported", False):
        return {"decision": "unsupported_category", "fix_result": result}
    return {"fix_result": result}
