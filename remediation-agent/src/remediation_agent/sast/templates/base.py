"""The `RuleTemplate` contract for deterministic, exact-rule-id SAST fixes.

A template is intentionally narrow: it claims exactly one Semgrep rule id
(`rule_id`) and knows how to mechanically rewrite the one code pattern that
rule id flags. It is not a general code-fixing tool -- if the flagged line
doesn't actually look like what the template knows how to rewrite (e.g. the
call already has an extra argument the template doesn't want to guess about),
it must raise `TemplateNotApplicableError` rather than force a rewrite, so
`SASTStrategy` can fall through to the LLM tier instead.
"""
from __future__ import annotations

from typing import Any

from s17code.coding.edit import EditLedger
from s17code.coding.workspace import Workspace


class TemplateNotApplicableError(ValueError):
    """This template's rule id matched, but the flagged code doesn't match
    the exact pattern the template knows how to rewrite.

    Distinct from `s17code.coding.edit.EditError`: `EditError` is raised by
    `apply_edit` itself when an anchor that *was* found isn't unique in the
    file (a real failure that must propagate). `TemplateNotApplicableError`
    is raised by the template *before* any `apply_edit` call, when it hasn't
    even found its expected pattern in `location["text"]` -- e.g. the call
    already carries a settings/config argument the template doesn't want to
    merge with. Callers (`strategies/sast.py`) catch this one specifically to
    fall through to the LLM-authored fix path.
    """


class RuleTemplate:
    """Base class for one curated, deterministic Semgrep-rule-id fix.

    Subclasses set the class attribute `rule_id` and override `apply`.
    `applies_to` has a sensible default (exact match on `finding["id"]`) that
    most templates won't need to override; it's a plain method (not a
    classmethod/staticmethod) so a subclass that wants fuzzier matching
    (e.g. a family of related rule ids) can still do so freely.
    """

    rule_id: str = ""

    def applies_to(self, finding: dict[str, Any]) -> bool:
        return finding.get("id") == self.rule_id

    def apply(
        self,
        workspace: Workspace,
        ledger: EditLedger,
        finding: dict[str, Any],
        location: dict[str, Any],
    ) -> dict[str, Any]:
        """Rewrite the flagged location. Returns a FixResult-shaped dict with
        `"fix_tier": "template"` set.

        Raises `TemplateNotApplicableError` if `location["text"]` doesn't
        actually contain the exact pattern this template knows how to
        rewrite. Lets `s17code.coding.edit.EditError` (ambiguous/absent
        anchor once handed to `apply_edit`) and
        `s17code.coding.guard.GuardError` (protected path) propagate
        unchanged -- both are real failures, not "fall through to the LLM"
        signals.
        """
        raise NotImplementedError
