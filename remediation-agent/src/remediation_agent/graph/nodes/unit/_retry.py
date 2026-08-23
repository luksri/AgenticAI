"""Shared retry-eligibility check for LLM-authored SAST fixes.

Only an LLM-authored fix (`fix_result["fix_tier"] == "llm"`) is retried when
a downstream gate rejects it. A deterministic template given the same
finding and the same code produces the identical, already-known-bad output
on a second attempt -- retrying it would burn the retry budget without
giving anything a real chance to change. (This distinction is only safe to
make here, after `generate_fix` has already succeeded and recorded which
tier it used; `generate_fix.py`'s own exception path can't reliably tell
whether a caught failure came from the template or the LLM tier, since a
template's `EditError`/`GuardError` propagate the same way an LLM path's do,
so that failure point is never retried -- see its docstring.)

Used by both `guard_check.py` and `validate_build_test.py`, since both
represent "the LLM's patch was bad in some fixable way" -- scope violation,
failed build, failed test, a security rule that still fires, an adversarial
rejection -- and all are equally worth feeding back to the model rather than
failing the unit outright.
"""
from __future__ import annotations

from typing import Any

from remediation_agent.config import get_settings


def build_retry_update(state: dict[str, Any], reason: str) -> dict[str, Any] | None:
    """A retry-triggering state update if this failure is worth retrying,
    else `None` (the caller should set a terminal `decision` instead).

    Callers must still call `workspace.reset()` themselves before returning
    either result -- this function only decides whether to retry, it doesn't
    touch the workspace.
    """
    fix_tier = (state.get("fix_result") or {}).get("fix_tier")
    if state["unit"]["category"] != "SAST" or fix_tier != "llm":
        return None

    attempt = state.get("retry_count", 0) + 1
    if attempt >= get_settings().sast_max_attempts:
        return None

    return {
        "retry_count": attempt,
        "retry_requested": True,
        "validation_feedback": reason,
    }
