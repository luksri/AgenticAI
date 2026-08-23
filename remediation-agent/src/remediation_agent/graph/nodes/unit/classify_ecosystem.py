"""Per-unit subgraph, step 1: check the finding's category is supported at
all, then detect which ecosystem adapter handles this repo.

The category check runs first and independently of ecosystem detection. Every
adapter's `locate_component` is built around `finding["component"]` (the SCA
shape); a non-SCA finding (no `component`, e.g. a future SAST/secrets entry)
would reach `locate` with an ecosystem correctly detected but nothing for it
to find, landing on the misleading `not_found`/"failed" bucket instead of the
accurate `unsupported_category`/"unsupported" one. Checking category support
here, before locate ever runs, keeps that distinction correct.
"""
from __future__ import annotations

from typing import Any

from s17code.coding.workspace import Workspace

from remediation_agent.ecosystems.registry import detect_ecosystem
from remediation_agent.strategies.registry import get as get_strategy
from remediation_agent.strategies.unsupported import UnsupportedStrategy


async def classify_ecosystem(state: dict) -> dict[str, Any]:
    category = state["unit"]["category"]
    if isinstance(get_strategy(category), UnsupportedStrategy):
        return {
            "decision": "unsupported_category",
            "error": f"category {category!r} not yet supported",
        }

    workspace = Workspace.open(state["workspace_root"])
    ecosystem = detect_ecosystem(workspace)
    if ecosystem is None:
        return {
            "decision": "unsupported_ecosystem",
            "error": "no registered ecosystem adapter detected this repo",
        }
    return {"ecosystem": ecosystem}
