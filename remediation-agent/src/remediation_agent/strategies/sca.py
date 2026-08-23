"""Deterministic SCA (dependency-version-bump) remediation strategy.

No LLM call in this default path: a unit's findings already agree on
`component` (that's the grouping key), so the only judgment call is which
`fixed_version` to apply when findings disagree (defensive -- shouldn't
normally happen since grouping keys on `component`). All locations found for
the unit's component are fixed to that one chosen version.
"""
from __future__ import annotations

from typing import Any

from .base import StrategyContext


def _version_sort_key(version: str) -> tuple[int, tuple]:
    """Dotted-version comparison key: numeric tuple when possible, else string.

    Splits on ".", compares tuples of ints where every part parses as an int;
    falls back to a plain string comparison otherwise. The leading int flags
    numeric keys as always greater than non-numeric ones so a real semver
    beats a garbage string deterministically rather than raising.
    """
    parts = version.split(".")
    try:
        return (1, tuple(int(p) for p in parts))
    except ValueError:
        return (0, (version,))


def _resolve_fixed_version(findings: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Pick the fixed_version to apply, and a message describing the choice."""
    candidates = [(f.get("fixed_version"), f) for f in findings if f.get("fixed_version")]
    if not candidates:
        return None, None

    distinct_versions = {version for version, _ in candidates}
    if len(distinct_versions) == 1:
        version, finding = candidates[0]
        return version, f"using fixed_version {version!r} from finding {finding.get('id')!r}"

    best_version, best_finding = max(candidates, key=lambda vf: _version_sort_key(vf[0]))
    message = (
        f"findings disagreed on fixed_version ({sorted(distinct_versions)!r}); "
        f"chose the highest, {best_version!r}, from finding {best_finding.get('id')!r}"
    )
    return best_version, message


class SCAStrategy:
    category = "SCA"

    def remediate(self, ctx: StrategyContext) -> dict[str, Any]:
        findings = ctx.unit.get("findings", [])
        fixed_version, choice_message = _resolve_fixed_version(findings)
        if not fixed_version:
            return {
                "supported": True,
                "changed_files": [],
                "old_version": None,
                "new_version": None,
                "message": "no finding in this unit carries a fixed_version; nothing to change",
            }

        template_finding = dict(findings[0]) if findings else {}
        template_finding["fixed_version"] = fixed_version

        changed_files: list[str] = []
        old_versions: list[str] = []
        already_satisfied = True
        for location in ctx.locations:
            result = ctx.adapter.apply_version_fix(ctx.workspace, ctx.ledger, template_finding, location)
            changed_files.extend(result.get("changed_files", []))
            if result.get("old_version"):
                old_versions.append(result["old_version"])
            if not result.get("already_satisfied"):
                already_satisfied = False

        # True only when every location was already at fixed_version -- if
        # even one genuinely changed, changed_files is non-empty and this
        # unit is a normal commit-worthy fix, not a no-op.
        nothing_to_commit = not changed_files and already_satisfied
        message = choice_message or f"applied fixed_version={fixed_version!r}"
        if nothing_to_commit:
            message = f"already at fixed_version={fixed_version!r}; no change needed"
        return {
            "supported": True,
            "changed_files": sorted(set(changed_files)),
            "old_version": old_versions[0] if old_versions else None,
            "new_version": fixed_version,
            "already_satisfied": nothing_to_commit,
            "message": message,
        }
