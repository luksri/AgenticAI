"""Pluggable ecosystem-adapter registration and detection.

Importing this module is enough to make `DotNetAdapter` and `JavaAdapter`
available: both are registered at import time below. A third language later
is one new adapter module plus one `register(...)` call here -- the graph
code never needs to change.
"""
from __future__ import annotations

from remediation_agent.config import register_allowed_commands
from s17code.coding.workspace import Workspace

from .base import EcosystemAdapter

_adapters: dict[str, EcosystemAdapter] = {}
_registration_order: list[str] = []


def register(adapter: EcosystemAdapter) -> None:
    """Register an adapter, and union its commands into the exec allowlist.

    Idempotent for the same adapter name: re-registering replaces the prior
    adapter instance in place (registration order is preserved).
    """
    if adapter.name not in _adapters:
        _registration_order.append(adapter.name)
    _adapters[adapter.name] = adapter
    register_allowed_commands(adapter.allowed_commands())


def get(name: str) -> EcosystemAdapter | None:
    return _adapters.get(name)


def detect_ecosystem(workspace: Workspace, forced: str | None = None) -> str | None:
    """The name of the first matching registered adapter, or None.

    If `forced` names a registered adapter, it is used without calling
    `detect()` at all. Otherwise every adapter's `detect()` is tried in
    registration order and the first match wins.
    """
    if forced and forced in _adapters:
        return forced
    for name in _registration_order:
        if _adapters[name].detect(workspace):
            return name
    return None


# Register the built-in adapters at import time.
from . import dotnet as _dotnet  # noqa: E402
from . import java as _java  # noqa: E402

register(_dotnet.DotNetAdapter())
register(_java.JavaAdapter())
