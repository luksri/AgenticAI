"""`settings.scope.allow`/`deny` fnmatch filtering for finding file paths."""
from __future__ import annotations

import fnmatch
from typing import Any


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.lstrip("/"))


def is_in_scope(relative_path: str, scope: dict[str, Any]) -> bool:
    """True if `relative_path` should be remediated under this `scope`.

    `scope` is ``{"allow": [...], "deny": [...]}`` of fnmatch glob patterns.
    A path matching any `deny` pattern is always excluded, even if it also
    matches `allow`. An empty (or missing) `allow` list means "allow
    everything not denied" -- the sample orchestrator payload ships
    placeholder values, so an unset allow list must not be treated as "deny
    everything".
    """
    scope = scope or {}
    allow = scope.get("allow") or []
    deny = scope.get("deny") or []
    path = relative_path or ""

    if any(_matches(path, pattern) for pattern in deny):
        return False
    if not allow:
        return True
    return any(_matches(path, pattern) for pattern in allow)
