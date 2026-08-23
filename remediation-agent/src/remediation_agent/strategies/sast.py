"""SAST (Semgrep) remediation strategy: template tier first, LLM fallback
second.

Unlike SCA's single deterministic path, a SAST unit's findings are fixed one
at a time with a two-tier dispatch: a curated, exact-rule-id template
(`sast.templates.registry`) if one claims the finding and its code actually
matches the pattern the template knows how to rewrite; otherwise an
LLM-authored patch (`sast.llm_fix.ask_llm_for_patch`), guided by curated
CWE-keyed guidance (`sast.guidance.guidance_for`) when available.

A SAST unit groups by `(category, file, line)` (see `grouping.py`), so in
practice a unit carries exactly one finding and one location -- but this
loop stays defensive (mirrors `sca.py` iterating over `ctx.locations`)
rather than hard-assuming that.

`remediate` is `async def` here (unlike `sca.py`'s plain sync method) because
the LLM-fallback path genuinely needs to `await` a chat-model call.
`graph/nodes/unit/generate_fix.py` awaits the result when
`strategy.remediate(ctx)` returns an awaitable and uses it directly
otherwise, so both this and `SCAStrategy`'s sync method satisfy the same
`RemediationStrategy` protocol. This matters at scale: a strategy that
blocked its calling thread synchronously (e.g. by running a fresh event loop
in a dedicated thread and joining it) would stall every other unit and job
sharing the same asyncio event loop for the duration of the LLM call --
exactly the concurrency this project's `execution/pool.py` is built to
provide. `await`ing in place keeps this cooperative instead.
"""
from __future__ import annotations

from typing import Any

from remediation_agent.llm.provider import get_chat_model
from remediation_agent.sast import guidance as sast_guidance
from remediation_agent.sast.llm_fix import ask_llm_for_patch
from remediation_agent.sast.templates import registry as template_registry
from remediation_agent.sast.templates.base import TemplateNotApplicableError

from .base import StrategyContext


class SASTStrategy:
    category = "SAST"

    async def remediate(self, ctx: StrategyContext) -> dict[str, Any]:
        findings = ctx.unit.get("findings", [])
        locations = ctx.locations

        changed_files: list[str] = []
        messages: list[str] = []
        used_llm = False
        chat_model = None  # constructed lazily, at most once per remediate() call

        for finding, location in zip(findings, locations):
            result: dict[str, Any] | None = None

            template = template_registry.get(finding)
            if template is not None:
                try:
                    result = template.apply(ctx.workspace, ctx.ledger, finding, location)
                except TemplateNotApplicableError:
                    # The rule id matched, but the flagged code doesn't match
                    # the exact pattern this template knows how to rewrite --
                    # fall through to the LLM tier. Any other exception
                    # (EditError, GuardError) is a real failure and is left
                    # to propagate out of this method, per the strategy
                    # contract.
                    result = None

            if result is None:
                if chat_model is None:
                    chat_model = get_chat_model()
                cwe_guidance = sast_guidance.guidance_for(finding.get("cwe_ids") or [])
                result = await ask_llm_for_patch(
                    chat_model, ctx.workspace, ctx.ledger, finding, location, cwe_guidance,
                    feedback=ctx.feedback,
                )
                used_llm = True

            changed_files.extend(result.get("changed_files", []))
            if result.get("message"):
                messages.append(result["message"])

        return {
            "supported": True,
            "changed_files": sorted(set(changed_files)),
            "old_version": None,
            "new_version": None,
            # The unit's overall fix_tier is "llm" if ANY finding in the unit
            # went through the LLM path -- the more conservative validation
            # gate (mandatory adversarial validation) applies to the whole
            # unit, not just the LLM-touched part of it.
            "fix_tier": "llm" if used_llm else "template",
            "message": "; ".join(messages) if messages else "no SAST findings located to fix",
        }
