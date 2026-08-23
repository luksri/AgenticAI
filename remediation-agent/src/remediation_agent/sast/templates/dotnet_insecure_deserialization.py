"""Template for Semgrep's `csharp.lang.security.insecure-deserialization.
insecure-deserialization` rule (CWE-502).

Rewrites an unguarded `JsonConvert.DeserializeObject<T>(x)` /
`JsonConvert.DeserializeObject(x)` call (Newtonsoft.Json) to pass an explicit,
safe `JsonSerializerSettings` with `TypeNameHandling.None` -- the same fix a
human would make: Newtonsoft resolves types named inside the JSON payload
itself when `TypeNameHandling` isn't pinned down, which is exactly what makes
this deserialization call attacker-controlled.

Deliberately narrow: if the call already passes a second argument (e.g. some
existing settings), this template refuses to guess how to merge with it and
raises `TemplateNotApplicableError` instead, handing off to the LLM tier.
"""
from __future__ import annotations

import re
from typing import Any

from s17code.coding.edit import EditLedger, apply_edit, read_code
from s17code.coding.workspace import Workspace

from .base import RuleTemplate, TemplateNotApplicableError

# The variable name for the injected settings object -- prefixed so it's
# unlikely to collide with anything already in scope.
_SETTINGS_VAR = "__remediationSerializerSettings"

# Matches `JsonConvert.DeserializeObject<...>(x)` (generic) or
# `JsonConvert.DeserializeObject(x)` (non-generic), where `x` is a single
# argument expression containing no comma or parenthesis -- i.e. no existing
# second (settings) argument. A call that already has a second argument
# (a comma inside the parens) will not match this pattern at all, which is
# exactly the "don't touch it" signal this template wants.
_CALL_PATTERN = re.compile(
    r"JsonConvert\.Deserialize(?:Object)?(?:\s*<[^>]*>)?\s*\(\s*([^,()]+?)\s*\)"
)


def _leading_whitespace(text: str) -> str:
    match = re.match(r"[ \t]*", text)
    return match.group(0) if match else ""


class DotNetInsecureDeserializationTemplate(RuleTemplate):
    rule_id = "csharp.lang.security.insecure-deserialization.insecure-deserialization"

    def apply(
        self,
        workspace: Workspace,
        ledger: EditLedger,
        finding: dict[str, Any],
        location: dict[str, Any],
    ) -> dict[str, Any]:
        text = location["text"]
        match = _CALL_PATTERN.search(text)
        if match is None:
            raise TemplateNotApplicableError(
                f"no bare (settings-free) JsonConvert.Deserialize(Object) call found "
                f"in {location.get('file')!r} line {location.get('line')!r}: {text!r}"
            )

        indent = _leading_whitespace(text)
        settings_decl = (
            f"{indent}var {_SETTINGS_VAR} = new JsonSerializerSettings "
            "{ TypeNameHandling = TypeNameHandling.None };"
        )

        # Insert `, __remediationSerializerSettings` just before the call's
        # closing parenthesis, leaving everything else on the line (the `;`,
        # any trailing comment, etc.) untouched.
        insert_at = match.end() - 1
        rewritten_line = text[:insert_at] + f", {_SETTINGS_VAR}" + text[insert_at:]
        new_text = f"{settings_decl}\n{rewritten_line}"

        # Read-before-edit: register a window around the flagged line as read
        # for THIS ledger before apply_edit is allowed to touch the file.
        line = location.get("line", 1)
        read_code(workspace, ledger, location["file"], offset=max(1, line - 2), limit=5)

        apply_edit(
            workspace,
            ledger,
            location["file"],
            old_string=text,
            new_string=new_text,
            replace_all=False,
        )

        return {
            "supported": True,
            "changed_files": [location["file"]],
            "old_version": None,
            "new_version": None,
            "fix_tier": "template",
            "message": (
                "rewrote insecure JsonConvert.DeserializeObject call to pass "
                "explicit safe JsonSerializerSettings"
            ),
        }
