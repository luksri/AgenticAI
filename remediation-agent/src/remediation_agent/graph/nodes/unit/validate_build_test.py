"""Per-unit subgraph, step 5: run the repo's own build/test gates on the fix.

`adapter.build_command(settings)` / `adapter.test_command(settings)` return
`list[list[str]] | None` -- each inner list is one no-shell argv step
(`settings.gates.build`/`test` strings are split only on literal `&&` by the
ecosystem adapter, matching `run_command`'s no-shell design); `None` means
the gate string was empty, so that gate is skipped entirely rather than
defaulted to something.

Any other shell metacharacter in a gate string (`;`, `|`, backticks,
redirects, ...) makes it unsafe to decompose into argv steps at all -- the
ecosystem adapter's `build_command`/`test_command` (via the shared
`split_gate_command` helper in `ecosystems/base.py`) raise
`GateCommandUnsafeError` for that case, before any command is ever run.
Separately, `s17code.coding.exec.run_command` itself refuses an individual
argv step that still contains a shell metacharacter or an unallowlisted
program (raises `CommandError`). Both are surfaced here as the same
`gate_command_unsafe` terminal decision, distinct from an ordinary
build/test failure (`fix_failed_validation`).
"""
from __future__ import annotations

import logging
from typing import Any

from s17code.coding.workspace import Workspace

from remediation_agent.coding.exec import CommandError, run_command
from remediation_agent.config import get_settings
from remediation_agent.ecosystems.base import GateCommandUnsafeError
from remediation_agent.ecosystems.registry import get as get_adapter
from remediation_agent.graph.nodes.unit._retry import build_retry_update

logger = logging.getLogger(__name__)


async def validate_build_test(state: dict) -> dict[str, Any]:
    workspace = Workspace.open(state["workspace_root"])
    adapter = get_adapter(state["ecosystem"])
    settings = state["settings"]

    build_result: dict[str, Any] | None = None
    test_result: dict[str, Any] | None = None

    try:
        build_steps = adapter.build_command(settings)
    except GateCommandUnsafeError as exc:
        workspace.reset()
        return {"decision": "gate_command_unsafe", "error": str(exc)}

    if build_steps:
        for step in build_steps:
            try:
                result = run_command(workspace, step)
            except CommandError as exc:
                workspace.reset()
                return {"decision": "gate_command_unsafe", "error": str(exc)}
            build_result = result.as_dict()
            if not result.ok:
                reason = (
                    "Your previous patch did not build. Build output:\n"
                    f"{build_result.get('stdout', '')}\n{build_result.get('stderr', '')}"
                )
                retry = build_retry_update(state, reason)
                workspace.reset()
                if retry is not None:
                    return retry
                return {
                    "decision": "fix_failed_validation",
                    "build_result": build_result,
                    "error": "build gate failed",
                }

    try:
        test_steps = adapter.test_command(settings)
    except GateCommandUnsafeError as exc:
        workspace.reset()
        return {"decision": "gate_command_unsafe", "error": str(exc), "build_result": build_result}

    if test_steps:
        for step in test_steps:
            try:
                result = run_command(workspace, step)
            except CommandError as exc:
                workspace.reset()
                return {"decision": "gate_command_unsafe", "error": str(exc)}
            test_result = result.as_dict()
            if not result.ok:
                reason = (
                    "Your previous patch built, but the test gate failed. Test "
                    f"output:\n{test_result.get('stdout', '')}\n{test_result.get('stderr', '')}"
                )
                retry = build_retry_update(state, reason)
                workspace.reset()
                if retry is not None:
                    return retry
                return {
                    "decision": "fix_failed_validation",
                    "build_result": build_result,
                    "test_result": test_result,
                    "error": "test gate failed",
                }

    is_sast = state["unit"]["category"] == "SAST"
    fix_tier = (state.get("fix_result") or {}).get("fix_tier")
    result: dict[str, Any] = {"build_result": build_result, "test_result": test_result}

    if is_sast:
        # Strongest available signal for a SAST fix: re-run the exact rule
        # that flagged each finding and confirm it no longer fires. Build/test
        # can't tell a deserialization call became safe; semgrep can. This
        # runs unconditionally for every SAST unit regardless of fix tier
        # (template-authored fixes get the same scrutiny as LLM-authored
        # ones) and fails closed: a finding semgrep_verify could not actually
        # verify (missing binary, timeout, bad output) is treated the same as
        # "the rule still fires", never silently accepted as fixed.
        from remediation_agent.sast.semgrep_verify import run_semgrep_verify

        per_finding = [
            await run_semgrep_verify(workspace, finding, settings)
            for finding in state["unit"]["findings"]
        ]
        semgrep_result = {"passed": all(r["passed"] for r in per_finding), "results": per_finding}
        result["semgrep_result"] = semgrep_result
        if not semgrep_result["passed"]:
            errors = [r["error"] for r in per_finding if r.get("error")]
            detail = "; ".join(errors) if errors else "rule still fires on the patched code"
            reason = (
                "Your previous patch built and passed tests, but re-running the "
                f"Semgrep rule that flagged this finding shows it still fires: {detail}. "
                "The vulnerable pattern is still present -- look again at what the rule "
                "actually detects, not just whether the code compiles."
            )
            retry = build_retry_update(state, reason)
            workspace.reset()
            if retry is not None:
                return {**result, **retry}
            return {
                **result,
                "decision": "fix_failed_validation",
                "error": f"semgrep re-verification failed: {detail}",
            }

    settings_obj = get_settings()
    # For SAST, an LLM-authored fix (fix_tier == "llm") requires the
    # adversarial validator unconditionally -- the user's explicit trust
    # model for this category: a template-authored fix and any other
    # category's fix keep the existing opt-in behavior
    # (`enable_adversarial_validation`), but no LLM-generated security patch
    # is accepted on build/test + semgrep alone.
    mandatory_adversarial = is_sast and fix_tier == "llm"
    adversarial_result = None
    if settings_obj.enable_adversarial_validation or mandatory_adversarial:
        try:
            from remediation_agent.llm.adversarial_validator import summarise, validate_fix
            from remediation_agent.llm.provider import get_chat_model

            chat_model = get_chat_model()
            requirement = (
                f"The fix for unit {state['unit']['unit_id']} was supposed to "
                f"remediate: {state['unit']['category']} on "
                f"{state['unit'].get('component') or state['unit']['file']}."
            )
            raw = await validate_fix(chat_model, workspace, workspace.diff(), requirement)
            adversarial_result = summarise(raw)
        except Exception as exc:
            if mandatory_adversarial:
                # This gate is not optional for an LLM-authored SAST fix --
                # unable to run it is not the same as passing it. Whether
                # this is worth a retry (vs. some fundamental issue that will
                # recur, e.g. the LLM provider being unreachable) is
                # ambiguous, but failing closed either way is right: an
                # unretried failure is safer than silently accepting an
                # unvalidated patch.
                reason = f"Mandatory adversarial validation could not run: {exc}. Try again."
                retry = build_retry_update(state, reason)
                workspace.reset()
                if retry is not None:
                    return {**result, **retry}
                return {
                    **result,
                    "decision": "adversarial_rejected",
                    "error": f"mandatory adversarial validation could not run: {exc}",
                }
            # Config-gated nice-to-have for every other case, not core to the
            # required build/test gate: a failure here (LLM unavailable, tool
            # loop error, etc.) must never fail the whole unit.
            logger.exception(
                "adversarial validation raised; ignoring (config-gated, non-core gate)"
            )

    if adversarial_result is not None:
        result["adversarial_result"] = adversarial_result
        if not adversarial_result["passed"]:
            reason = (
                "Your previous patch built, passed tests, and passed semgrep "
                f"re-verification, but an independent review rejected it: "
                f"{adversarial_result['summary']}"
            )
            retry = build_retry_update(state, reason)
            workspace.reset()
            if retry is not None:
                return {**result, **retry}
            return {**result, "decision": "adversarial_rejected", "error": adversarial_result["summary"]}

    return {**result, "retry_requested": False}
