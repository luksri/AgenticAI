"""Pluggable strategy registration, keyed by `finding["category"]`.

`get()` never raises for an unknown category -- it falls back to the shared
`UnsupportedStrategy` instance, which is what makes an unrecognized category
degrade cleanly instead of crashing the run.
"""
from __future__ import annotations

from .base import RemediationStrategy
from .unsupported import UnsupportedStrategy

_strategies: dict[str, RemediationStrategy] = {}
_unsupported = UnsupportedStrategy()


def register(strategy: RemediationStrategy) -> None:
    _strategies[strategy.category] = strategy


def get(category: str) -> RemediationStrategy:
    return _strategies.get(category, _unsupported)


# Register the built-in strategies at import time.
from . import sca as _sca  # noqa: E402
from . import sast as _sast  # noqa: E402

register(_sca.SCAStrategy())
register(_sast.SASTStrategy())
