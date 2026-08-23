"""Parent-graph node: the `Send` fan-out target that runs one unit's subgraph.

`state` here is the per-unit `UnitState` dict built by `fanout_units` in
`graph/build.py` (one `Send("remediate_unit", {...})` per `RemediationUnit`).

Why the per-`workspace_root` lock: multiple units for the same repo are
logically parallel (they arrive as separate `Send` invocations, and LangGraph
may run them concurrently), but they all share one on-disk checkout via
`Workspace`. Concurrent `apply_edit`/`git branch`/`git commit`/
`workspace.reset()` calls against the same working tree would race and
corrupt it -- there is no `git worktree` support in session-17's `exec.py`
allowlist to give each unit its own checkout. So units for one repo are
serialized here. Real parallelism at 2000+-repo scale comes from many
*different* repos running concurrently via the worker pool
(`execution/pool.py`), each with its own `workspace_root` and therefore its
own lock -- not from parallelizing units within a single repo.
"""
from __future__ import annotations

from typing import Any

from remediation_agent.execution.locks import get_workspace_lock
from remediation_agent.graph.unit_subgraph import UNIT_GRAPH


async def remediate_unit(state: dict) -> dict[str, Any]:
    lock = get_workspace_lock(state["workspace_root"])
    async with lock:
        result = await UNIT_GRAPH.ainvoke(state)
    return {"unit_results": [result]}
