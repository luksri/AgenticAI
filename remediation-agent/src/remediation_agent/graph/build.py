"""The parent graph: one orchestrator payload, end to end.

    START -> ingest -> (route_after_ingest) -> plan_findings
          -> (fanout_units) -> remediate_unit* -> aggregate -> END

`build_graph` is a function, not a module-level compiled singleton (compare
`graph/unit_subgraph.py`'s `UNIT_GRAPH`), so callers -- the worker pool or
the CLI -- can pass in whatever checkpointer they want, or `None` for no
persistence (used by `cli.py run-once`).
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from remediation_agent.graph.nodes.aggregate import aggregate
from remediation_agent.graph.nodes.ingest import ingest
from remediation_agent.graph.nodes.plan_findings import plan_findings
from remediation_agent.graph.nodes.remediate_unit import remediate_unit
from remediation_agent.schemas.state import RunState


def route_after_ingest(state: dict) -> str:
    """`ingest` sets `ingest_error` on a bad payload / unusable workspace --
    route straight to END rather than fanning out over findings that were
    never validated."""
    return END if state.get("ingest_error") else "plan_findings"


def fanout_units(state: dict) -> str | list[Send]:
    """One `Send("remediate_unit", ...)` per planned unit. A payload with no
    in-scope/severity-matching findings produces an empty `units` list --
    route straight to `aggregate` instead of an empty `Send` list, so the run
    still completes cleanly with an empty (but well-formed) `run_summary`."""
    units = state.get("units") or []
    if not units:
        return "aggregate"
    return [
        Send(
            "remediate_unit",
            {
                "unit": unit,
                "run_context": state["run_context"],
                "settings": state["settings"],
                "workspace_root": state["workspace_root"],
            },
        )
        for unit in units
    ]


def build_graph(checkpointer: Any | None = None):
    graph = StateGraph(RunState)

    graph.add_node("ingest", ingest)
    graph.add_node("plan_findings", plan_findings)
    graph.add_node("remediate_unit", remediate_unit)
    graph.add_node("aggregate", aggregate)

    graph.add_edge(START, "ingest")
    graph.add_conditional_edges(
        "ingest", route_after_ingest, {"plan_findings": "plan_findings", END: END}
    )
    graph.add_conditional_edges(
        "plan_findings", fanout_units, {"aggregate": "aggregate", "remediate_unit": "remediate_unit"}
    )
    graph.add_edge("remediate_unit", "aggregate")
    graph.add_edge("aggregate", END)

    return graph.compile(checkpointer=checkpointer)
