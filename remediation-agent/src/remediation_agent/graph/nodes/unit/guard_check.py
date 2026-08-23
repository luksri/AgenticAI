"""Per-unit subgraph, step 4: business-level scope check on what changed.

Distinct from session-17's automatic `guard_path` (which already ran inside
`apply_edit`/`create_file` in `generate_fix` and refuses protected paths like
`tests/**`). This is a second, independent check: every file the strategy
actually touched must also be inside the orchestrator payload's
`settings.scope.allow`/outside `scope.deny` -- nothing unexpected got
touched, from the caller's own scope contract, not just session-17's
built-in protected-path list.
"""
from __future__ import annotations

from typing import Any

from s17code.coding.workspace import Workspace

from remediation_agent.graph.nodes.unit._retry import build_retry_update
from remediation_agent.scope import is_in_scope


async def guard_check(state: dict) -> dict[str, Any]:
    changed_files = state["fix_result"].get("changed_files", [])
    scope = state["settings"].get("scope", {})

    for path in changed_files:
        if not is_in_scope(path, scope):
            reason = (
                f"Your previous patch modified {path!r}, which is outside the "
                "allowed scope for this fix. Only modify "
                f"{state['unit']['file']!r} (the file containing the flagged "
                "finding)."
            )
            retry = build_retry_update(state, reason)
            Workspace.open(state["workspace_root"]).reset()
            if retry is not None:
                return retry
            return {
                "decision": "guard_blocked",
                "error": f"changed file outside allowed scope: {path}",
            }

    # Explicitly clear stale retry/downstream-gate fields from a previous
    # attempt on every pass through here (first attempt or a retry) so a
    # terminal report never mixes this attempt's outcome with a prior one's
    # leftover build_result/semgrep_result/etc.
    return {
        "guard_result": {"ok": True},
        "retry_requested": False,
        "build_result": None,
        "test_result": None,
        "semgrep_result": None,
        "adversarial_result": None,
    }
