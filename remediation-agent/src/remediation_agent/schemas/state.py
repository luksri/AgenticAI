"""LangGraph state schemas for the parent graph and the per-unit subgraph.

Kept as plain TypedDicts (LangGraph's native state shape) rather than pydantic
models: LangGraph applies reducers (e.g. `operator.add` below) per key on
plain dict-like state, and every value here must stay checkpointer-serializable
(plain str/dict/list, never a live `Workspace`/`EditLedger`/db-connection
object -- those are always re-opened locally inside each node from
`workspace_root`).
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

# Terminal decisions a remediation unit can land on. Every one of these must
# be reachable without raising -- "never crash the run, always report a
# structured result" is enforced at the graph level via routing on this field.
UnitDecision = Literal[
    "pass",
    "unsupported_ecosystem",
    "unsupported_category",
    "not_found",
    "fix_failed",
    "guard_blocked",
    "fix_failed_validation",
    "gate_command_unsafe",
    "adversarial_rejected",
]


class RemediationUnit(TypedDict):
    """One or more findings grouped so a single fix closes all of them.

    Produced by grouping.group_findings_into_units(). `unit_id` is a
    deterministic short hash of the group key, so reruns on the same
    commit/repo produce the same id (and therefore the same branch name),
    which is what makes dedup and "did we already fix this" meaningful.
    """

    unit_id: str
    category: str
    component: str | None
    # Set for line-located findings (SAST) grouped by (category, file, line);
    # None for component-grouped (SCA) or file-only-grouped units.
    line: int | None
    file: str
    findings: list[dict[str, Any]]


class RunState(TypedDict, total=False):
    """Parent graph state: one orchestrator payload, end to end."""

    run_context: dict[str, Any]
    source: dict[str, Any]
    settings: dict[str, Any]
    workspace_root: str
    findings: list[dict[str, Any]]
    units: list[RemediationUnit]
    # `Send` fan-out into `remediate_unit` returns partial state updates that
    # LangGraph merges back with this reducer -- every parallel unit's result
    # is concatenated, never overwritten.
    unit_results: Annotated[list[dict[str, Any]], operator.add]
    run_summary: dict[str, Any] | None
    ingest_error: str | None


class UnitState(TypedDict, total=False):
    """Per-unit subgraph state: exactly one RemediationUnit's journey."""

    unit: RemediationUnit
    run_context: dict[str, Any]
    settings: dict[str, Any]
    workspace_root: str

    ecosystem: str | None
    locations: list[dict[str, Any]] | None
    fix_result: dict[str, Any] | None
    guard_result: dict[str, Any] | None
    build_result: dict[str, Any] | None
    test_result: dict[str, Any] | None
    adversarial_result: dict[str, Any] | None
    # SAST units only: re-running the flagged Semgrep rule(s) against the
    # patched file(s), confirming they no longer fire.
    semgrep_result: dict[str, Any] | None

    decision: UnitDecision | None
    error: str | None
    branch: str | None
    commit_sha: str | None

    # Retry loop (LLM-authored SAST fixes only -- see
    # graph/nodes/unit/_retry.py). `retry_requested` is the signal the
    # per-unit subgraph's routing reads after `guard_check`/
    # `validate_build_test`: True loops back to `generate_fix` with
    # `validation_feedback` describing what to fix; every node on that path
    # explicitly sets it False on its own success/pass-through, so a stale
    # True from an earlier attempt is never misread as "retry again" once a
    # later attempt actually succeeds.
    retry_count: int | None
    retry_requested: bool | None
    validation_feedback: str | None
