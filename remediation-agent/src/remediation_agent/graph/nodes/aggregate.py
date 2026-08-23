"""Parent-graph terminal node: bucket unit results into the run's output.

Pure, no side effects -- kept as its own checkpointed step so a resume after
a crash never recomputes a fix that already succeeded (`unit_results` is
already durable state by the time this node runs). `run_summary` IS the
remediation output the user asked for; there is no PR step, confirmed out of
scope.
"""
from __future__ import annotations

from typing import Any

UNSUPPORTED_DECISIONS = {"unsupported_ecosystem", "unsupported_category"}
# Every other non-"pass" UnitDecision is a failure: "not_found", "fix_failed",
# "guard_blocked", "fix_failed_validation", "gate_command_unsafe",
# "adversarial_rejected".


async def aggregate(state: dict) -> dict[str, Any]:
    unit_results = state.get("unit_results") or []

    passed: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for result in unit_results:
        decision = result.get("decision")
        if decision == "pass":
            passed.append(result)
        elif decision in UNSUPPORTED_DECISIONS:
            unsupported.append(result)
        else:
            failed.append(result)

    # Not exclusively CVE ids: a CVE id for SCA (Trivy) findings, a rule id
    # for SAST (Semgrep) findings -- whatever `finding["id"]` holds for that
    # tool.
    findings_closed = sorted(
        {
            finding.get("id")
            for result in passed
            for finding in (result.get("unit") or {}).get("findings", [])
            if finding.get("id")
        }
    )

    run_summary = {
        "run_context": state.get("run_context"),
        "total_units": len(unit_results),
        "passed": passed,
        "unsupported": unsupported,
        "failed": failed,
        "findings_closed": findings_closed,
    }
    return {"run_summary": run_summary}
