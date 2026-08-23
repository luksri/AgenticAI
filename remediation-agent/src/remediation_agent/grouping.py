"""Findings -> RemediationUnit list: filtering, grouping, deterministic ids.

Fully deterministic and side-effect free -- no workspace/network access, so
it's safe to call from the `plan_findings` graph node with plain dict/list
state.
"""
from __future__ import annotations

import hashlib
from typing import Any

from remediation_agent.schemas.state import RemediationUnit
from remediation_agent.scope import is_in_scope


def _max_risk_score(unit: RemediationUnit) -> float:
    return max((f.get("risk", {}).get("score") or 0 for f in unit["findings"]), default=0)


def group_findings_into_units(
    findings: list[dict[str, Any]], settings: dict[str, Any]
) -> list[RemediationUnit]:
    """Filter by severity/scope, group into units, sort by descending risk.

    1. Drop findings whose `severity` is not in `settings["severity"]` (an
       empty severity list means no filter) or whose `file` fails
       `scope.is_in_scope`.
    2. Group by, in order of preference: `(category, component)` when a
       component is present (the SCA case -- every CVE against the same
       package becomes one unit); else `(category, file, line)` when a line
       number is present (the SAST case -- one vulnerable location is one
       remediation unit, same "smallest safe blast radius" reasoning as
       one-package-per-unit for SCA); else `(category, file)` (fallback for
       any future category with neither concept).
    3. `unit_id` = first 12 hex chars of
       ``sha1(f"{category}:{key}".encode()).hexdigest()`` -- deterministic,
       so reruns on the same repo/commit produce the same id.
    4. Units are sorted by descending max risk score across their member
       findings (`finding["risk"]["score"]`, default 0), so higher-risk fixes
       are processed first when concurrency is constrained.
    """
    severity_filter = set(settings.get("severity") or [])
    scope = settings.get("scope") or {}

    filtered = [
        finding
        for finding in findings
        if (not severity_filter or finding.get("severity") in severity_filter)
        and is_in_scope(finding.get("file", ""), scope)
    ]

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    order: list[tuple[str, ...]] = []
    for finding in filtered:
        category = finding.get("category", "")
        component = finding.get("component")
        line = finding.get("line")
        if component:
            key = (category, "component", component)
        elif line is not None:
            key = (category, "line", finding.get("file", ""), str(line))
        else:
            key = (category, "file", finding.get("file", ""))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(finding)

    units: list[RemediationUnit] = []
    for key in order:
        members = groups[key]
        category = key[0]
        unit_id = hashlib.sha1(f"{category}:{':'.join(key[1:])}".encode()).hexdigest()[:12]
        units.append(
            RemediationUnit(
                unit_id=unit_id,
                category=category,
                component=members[0].get("component"),
                line=members[0].get("line"),
                file=members[0].get("file", ""),
                findings=members,
            )
        )

    units.sort(key=_max_risk_score, reverse=True)
    return units
