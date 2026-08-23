"""Per-`workspace_root` locks so units for the same repo checkout serialize.

Used by `graph/nodes/remediate_unit.py` -- see that module's docstring for
why. Module-level dict rather than an instance attribute so every caller in
the process (worker pool coroutines, tests, `run-once`) shares the same lock
for the same root, regardless of how many times a graph gets built/invoked.
"""
from __future__ import annotations

import asyncio

_locks: dict[str, asyncio.Lock] = {}


def get_workspace_lock(workspace_root: str) -> asyncio.Lock:
    lock = _locks.get(workspace_root)
    if lock is None:
        lock = asyncio.Lock()
        _locks[workspace_root] = lock
    return lock
