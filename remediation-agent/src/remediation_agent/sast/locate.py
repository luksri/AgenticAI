"""Generic file:line location for SAST findings.

Ecosystem adapters locate an SCA finding's manifest entry; that concept
doesn't exist for a SAST finding, which instead carries `file` + `line`. This
is deliberately not ecosystem-specific -- reading a line out of a source file
needs no build-tool knowledge.

Mirrors the ecosystem adapters' own convention: a plain read here (not
`read_code`), because no `EditLedger` exists yet at the `locate` step. The
`read_code` call that actually satisfies read-before-edit happens later,
inside the strategy, right before `apply_edit` -- exactly like
`DotNetAdapter`/`JavaAdapter` already do.

Unlike SCA's `locate_component` (which re-derives its target by searching
current content for a component *name*, so it's naturally immune to line
drift), a SAST finding's `line` is a position captured whenever the
orchestrator's scan ran. If the file has since had lines inserted or removed
above that point, the line number can still be in-bounds while pointing at
completely unrelated code -- silently handing the wrong text to a template
or an LLM to "fix." `finding["snippet"]` (the code as originally scanned) is
the one piece of evidence available to catch this: when it's present, it
must match what's actually at that line now, or this function does not
guess.
"""
from __future__ import annotations

from typing import Any

from s17code.coding.workspace import Workspace


def _normalize(text: str) -> str:
    """Collapse whitespace runs so a comparison isn't defeated by
    indentation/formatting differences that don't change the code."""
    return " ".join(text.split())


def locate_by_line(workspace: Workspace, finding: dict[str, Any]) -> list[dict[str, Any]]:
    relative = finding.get("file")
    line_number = finding.get("line")
    if not relative or not line_number:
        return []

    try:
        path = workspace.resolve(relative)
    except Exception:
        return []
    if not path.is_file():
        return []

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not (1 <= line_number <= len(lines)):
        return []

    drifted = False
    snippet = finding.get("snippet")
    if snippet and snippet.strip():
        normalized_snippet = _normalize(snippet)
        if _normalize(lines[line_number - 1]) != normalized_snippet:
            # The line number no longer points at the scanned code. Search
            # the whole file for exactly where it moved to: a single
            # unambiguous match means the file just shifted (safe to
            # relocate); zero matches means the flagged code is genuinely
            # gone (nothing to fix); more than one match is exactly the
            # anchor-ambiguity `apply_edit` itself refuses elsewhere in this
            # project, for the same reason -- guessing which one the
            # finding meant would be worse than refusing.
            matches = [
                idx + 1 for idx, candidate in enumerate(lines)
                if _normalize(candidate) == normalized_snippet
            ]
            if len(matches) != 1:
                return []
            line_number = matches[0]
            drifted = True

    location: dict[str, Any] = {
        "file": relative,
        "pattern_kind": "sast_line",
        "line": line_number,
        # The line's current text on disk -- this, not the payload's
        # snippet, is what a fix must anchor against.
        "text": lines[line_number - 1],
    }
    if drifted:
        # Surfaced for auditability in the reported unit result -- doesn't
        # change how the fix is validated, every gate still runs the same.
        location["line_drifted"] = True
    return [location]
