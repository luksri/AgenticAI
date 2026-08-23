"""Per-unit subgraph, step 2: locate where each finding lives.

Two shapes of "where": an SCA finding names a `component` (a package) that
lives in a manifest the ecosystem adapter knows how to search; a SAST finding
names a `file`+`line` (actual vulnerable code) that needs no ecosystem
knowledge at all, just a plain read. Branching on the finding's own shape
here -- rather than routing on `category` -- keeps this correct even for a
future category that mixes both within one payload.
"""
from __future__ import annotations

from typing import Any

from s17code.coding.workspace import Workspace

from remediation_agent.ecosystems.registry import get as get_adapter
from remediation_agent.sast.locate import locate_by_line


async def locate(state: dict) -> dict[str, Any]:
    workspace = Workspace.open(state["workspace_root"])
    adapter = get_adapter(state["ecosystem"])

    locations: list[dict[str, Any]] = []
    for finding in state["unit"]["findings"]:
        if finding.get("component") and adapter is not None:
            locations.extend(adapter.locate_component(workspace, finding))
        elif finding.get("line") is not None:
            locations.extend(locate_by_line(workspace, finding))

    if not locations:
        return {"decision": "not_found", "locations": []}
    return {"locations": locations}
