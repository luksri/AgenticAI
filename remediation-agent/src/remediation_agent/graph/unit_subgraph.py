"""The per-unit subgraph: one `RemediationUnit`'s journey from ecosystem
detection to a terminal decision.

Compiled once at import time as `UNIT_GRAPH` -- unlike the parent graph
(`graph/build.py`'s `build_graph`), this one takes no checkpointer of its
own and genuinely is a singleton: the parent graph's checkpointer covers the
whole run, including this subgraph's sub-invocations (each `remediate_unit`
parent node calls `UNIT_GRAPH.ainvoke(...)` directly rather than compiling
it as a LangGraph "subgraph node", so its steps aren't separately
checkpointed -- if a unit is interrupted mid-flight the whole unit reruns
from `classify_ecosystem` on resume, which is fine since every node here is
idempotent/side-effect-safe on retry: failing paths always call
`workspace.reset()` before returning).

Every node from `classify_ecosystem` through `validate_build_test` is
followed by a conditional edge that checks `state.get("decision")`: if a
node already set a terminal decision, control jumps straight to `decide`;
otherwise it proceeds to the next node in sequence. This is the mechanism
that guarantees every unit reaches a terminal, structured result without any
node needing to raise.

`guard_check` and `validate_build_test` add a third possibility on top of
that: for an LLM-authored SAST fix a gate rejects, instead of a terminal
decision they can request a bounded retry (`_route_with_retry`), looping
back to `generate_fix` with `state["validation_feedback"]` describing what
was wrong, up to `Settings.sast_max_attempts` total attempts (see
`_retry.py`). A deterministic template fix is never retried this way -- see
`_retry.py`'s docstring for why.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from remediation_agent.graph.nodes.unit.classify_ecosystem import classify_ecosystem
from remediation_agent.graph.nodes.unit.decide import decide
from remediation_agent.graph.nodes.unit.generate_fix import generate_fix
from remediation_agent.graph.nodes.unit.guard_check import guard_check
from remediation_agent.graph.nodes.unit.locate import locate
from remediation_agent.graph.nodes.unit.validate_build_test import validate_build_test
from remediation_agent.schemas.state import UnitState


def _route_or_decide(next_node: str):
    """Build a conditional-edge function: go to `next_node` unless a decision
    was already set, in which case skip straight to `decide`."""

    def _route(state: dict) -> str:
        return "decide" if state.get("decision") else next_node

    return _route


def _route_with_retry(next_node: str):
    """Like `_route_or_decide`, plus a third destination: loop back to
    `generate_fix` when `guard_check`/`validate_build_test` requested a retry
    (an LLM-authored SAST fix, rejected by a downstream gate, still has
    retry budget left -- see `_retry.py`). A cycle back to an earlier node is
    a normal LangGraph pattern (this is a bounded reflection loop, not
    recursion in the Python sense): `generate_fix` runs again with
    `state["validation_feedback"]` describing what to fix, then flows
    forward through the same edges as a first attempt.

    `decision` still takes priority over `retry_requested`: a node earlier
    in this same pass (or `guard_check`/`validate_build_test` itself,
    setting a terminal decision because retry budget is exhausted) always
    wins.
    """

    def _route(state: dict) -> str:
        if state.get("decision"):
            return "decide"
        if state.get("retry_requested"):
            return "generate_fix"
        return next_node

    return _route


def _build_unit_graph():
    graph = StateGraph(UnitState)

    graph.add_node("classify_ecosystem", classify_ecosystem)
    graph.add_node("locate", locate)
    graph.add_node("generate_fix", generate_fix)
    graph.add_node("guard_check", guard_check)
    graph.add_node("validate_build_test", validate_build_test)
    graph.add_node("decide", decide)

    graph.set_entry_point("classify_ecosystem")

    graph.add_conditional_edges(
        "classify_ecosystem",
        _route_or_decide("locate"),
        {"locate": "locate", "decide": "decide"},
    )
    graph.add_conditional_edges(
        "locate",
        _route_or_decide("generate_fix"),
        {"generate_fix": "generate_fix", "decide": "decide"},
    )
    graph.add_conditional_edges(
        "generate_fix",
        _route_or_decide("guard_check"),
        {"guard_check": "guard_check", "decide": "decide"},
    )
    graph.add_conditional_edges(
        "guard_check",
        _route_with_retry("validate_build_test"),
        {"validate_build_test": "validate_build_test", "decide": "decide", "generate_fix": "generate_fix"},
    )
    graph.add_conditional_edges(
        "validate_build_test",
        _route_with_retry("decide"),
        {"decide": "decide", "generate_fix": "generate_fix"},
    )
    graph.add_edge("decide", END)

    return graph.compile()


UNIT_GRAPH = _build_unit_graph()
