"""Parent-graph node: group validated findings into remediation units."""
from __future__ import annotations

from typing import Any

from remediation_agent.grouping import group_findings_into_units


async def plan_findings(state: dict) -> dict[str, Any]:
    units = group_findings_into_units(state["findings"], state["settings"])
    return {"units": units}
