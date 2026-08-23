"""LLM-authored patch generation for SAST findings with no curated template.

Follows `llm/adversarial_validator.py`'s established conventions for talking
to a `BaseChatModel`: a disciplined system prompt, read-only tool access
bound via LangChain tool-calling, a bounded tool-calling loop, and strict
JSON parsing with a clear failure mode -- rather than inventing a second
style.

Unlike the validator, this function isn't "no hands": it does eventually
apply an edit. But the boundary is the same in spirit -- the tools available
during the loop are read-only (`read_file`, `grep`, `glob`, `run`; no
`apply_edit`/`create_file`), and the actual write only happens once, after
the loop, against whichever `old_string`/`new_string` the model's final
non-tool-calling response proposes. Every `read_file` call during the loop
goes through the same `EditLedger` as the initial context read, so whatever
region the model ends up anchoring on has genuinely been read before
`apply_edit` is asked to touch it, satisfying read-before-edit regardless of
which file/region the model explored last.

The proposed edit is still constrained to `location["file"]` (the file
containing the flagged line) even though the model can read/search/run
elsewhere for context -- see SYSTEM_PROMPT. This keeps the change's blast
radius predictable; `guard_check.py` would catch an edit to any other file
as a scope violation anyway, but the point of a harness is to make the model
not attempt that in the first place, not merely to catch it after the fact.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from s17code.coding.edit import EditLedger, apply_edit, read_code
from s17code.coding.exec import CommandError, run_command
from s17code.coding.search import glob_files, grep_code
from s17code.coding.workspace import Workspace

SYSTEM_PROMPT = (
    "You are patching one specific, already-identified security "
    "vulnerability in an existing codebase. This is not a general "
    "refactoring task: you must make the smallest possible change that "
    "fixes the exact flagged issue, and nothing else.\n\n"
    "You have read-only tools to investigate before proposing a fix: read "
    "more of this file or others, search the repository for related code "
    "(other call sites, type definitions, existing patterns for this kind "
    "of fix elsewhere in the codebase), and run allowlisted commands. Use "
    "them if the source window you were shown isn't enough to propose a "
    "confident, correct fix -- do not guess when you could check. These "
    "tools cannot apply your patch; only your final answer does that.\n\n"
    "Your proposed patch must still apply to the file containing the "
    "flagged finding, even if you read or searched other files for "
    "context. Do not propose changes to any other file.\n\n"
    "When you are ready to answer, respond with JSON only, no prose "
    "outside the JSON object, and no further tool calls, in exactly this "
    "shape:\n"
    '{"old_string": str, "new_string": str, "explanation": str}\n\n'
    "You must choose `old_string` as text that appears VERBATIM in code you "
    "have actually read (via the initial window or a `read_file` tool "
    "call) -- exact characters, exact whitespace, exact indentation. The "
    "edit will be rejected if it does not match exactly or if you never "
    "read that region, so do not paraphrase or reformat the code you are "
    "anchoring on, and do not anchor on code you haven't read. `old_string` "
    "must be unique within the file -- include enough surrounding context "
    "to identify one exact location if the flagged line alone could appear "
    "more than once. `explanation` is a one- or two-sentence description of "
    "what you changed and why it closes the vulnerability."
)

MAX_TOOL_ITERATIONS = 6
MAX_RESPONSE_CHARS_IN_ERROR = 500


class LLMFixError(ValueError):
    """The model's proposed patch was missing, malformed, or unparseable, or
    the model never reached a final answer.

    Raised when the chat model's response doesn't parse as JSON, doesn't
    contain the required `old_string`/`new_string` keys, or the tool-calling
    loop runs out of iterations without a final non-tool-calling response.
    Never silently proceeds with a partial/guessed patch. Allowed to
    propagate out of `SASTStrategy.remediate` exactly like
    `EditError`/`GuardError` -- `generate_fix.py`'s except clause is expected
    to catch it alongside them.
    """


def _build_context_block(
    finding: dict[str, Any],
    location: dict[str, Any],
    read_result: dict[str, Any],
    guidance: str | None,
    feedback: str | None,
) -> str:
    cwe_ids = finding.get("cwe_ids") or []
    snippet = finding.get("snippet") or location.get("text") or ""
    parts = [
        f"Vulnerability: {finding.get('title') or finding.get('id')}",
        f"Rule id: {finding.get('id')}",
        f"CWE ids: {', '.join(cwe_ids) if cwe_ids else '(none provided)'}",
        f"File: {location.get('file')}",
        f"Flagged line number: {location.get('line')}",
        f"Flagged code (as originally scanned): {snippet}",
        "",
        "Source window (line-numbered, already read):",
        read_result["text"],
    ]
    if guidance:
        parts += [
            "",
            "The following curated guidance applies to this vulnerability class:",
            guidance,
        ]
    if feedback:
        parts += [
            "",
            "You already attempted this fix once and it was rejected. Do not "
            "repeat the same mistake:",
            feedback,
        ]
    return "\n".join(parts)


def _parse_patch_response(content: Any) -> dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        parsed = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError) as exc:
        raise LLMFixError(
            f"LLM patch response was not parseable JSON: {exc}; "
            f"raw response: {text[:MAX_RESPONSE_CHARS_IN_ERROR]!r}"
        ) from exc

    if not isinstance(parsed, dict):
        raise LLMFixError(f"LLM patch response JSON was not an object: {type(parsed).__name__}")

    old_string = parsed.get("old_string")
    new_string = parsed.get("new_string")
    if not isinstance(old_string, str) or not old_string:
        raise LLMFixError(
            f"LLM patch response missing a non-empty 'old_string': {parsed!r}"
        )
    if not isinstance(new_string, str) or not new_string:
        raise LLMFixError(
            f"LLM patch response missing a non-empty 'new_string': {parsed!r}"
        )
    parsed.setdefault("explanation", "LLM-generated patch")
    return parsed


async def ask_llm_for_patch(
    chat_model: BaseChatModel,
    workspace: Workspace,
    ledger: EditLedger,
    finding: dict[str, Any],
    location: dict[str, Any],
    guidance: str | None,
    *,
    feedback: str | None = None,
) -> dict[str, Any]:
    """Ask `chat_model` for a minimal patch closing `finding`, and apply it.

    Reads a wider window around the flagged line first (both to give the
    model real context and to satisfy read-before-edit for whatever it ends
    up anchoring on), then runs a bounded tool-calling loop so the model can
    investigate further (other call sites, related files, allowlisted
    commands) before proposing `{"old_string", "new_string", "explanation"}`.
    `feedback`, when set (a retry of a previously rejected attempt -- see
    `graph/nodes/unit/_retry.py`), is included in the prompt so the model
    doesn't repeat the same mistake.

    Raises `LLMFixError` if the model's final response doesn't parse into
    the expected shape, or if the loop exhausts `MAX_TOOL_ITERATIONS` without
    ever producing one. Lets `s17code.coding.edit.EditError` (anchor not
    found or not unique) propagate unchanged out of the `apply_edit` call --
    that's a real failure, not something to retry silently inside this
    function (the caller's retry loop, driven by a downstream validation
    gate, is where a second attempt happens, not here).
    """
    line = location.get("line", 1)
    read_result = read_code(
        workspace, ledger, location["file"], offset=max(1, line - 10), limit=25
    )

    @tool
    def read_file(relative_path: str, offset: int = 1, limit: int | None = None) -> dict:
        """Read part of a file in the workspace (ranged by line, 1-indexed).

        Counts as having read that region: it becomes eligible to anchor a
        patch on.
        """
        return read_code(workspace, ledger, relative_path, offset=offset, limit=limit)

    @tool
    def grep(pattern: str, path_glob: str = "*", limit: int = 60, ignore_case: bool = False) -> dict:
        """Search file contents in the workspace for a regex pattern."""
        return grep_code(workspace, pattern, path_glob=path_glob, limit=limit, ignore_case=ignore_case)

    @tool
    def glob(pattern: str, limit: int = 200) -> dict:
        """Find files in the workspace matching a glob pattern."""
        return glob_files(workspace, pattern, limit=limit)

    @tool
    def run(command: list[str], timeout: int = 120) -> dict:
        """Run one allowlisted, no-shell command inside the workspace and
        return its result. Investigation only -- this cannot apply your patch.
        """
        try:
            result = run_command(workspace, command, timeout=timeout)
        except CommandError as exc:
            return {"error": str(exc)}
        return result.as_dict()

    tools = [read_file, grep, glob, run]
    tools_by_name = {t.name: t for t in tools}
    bound_model = chat_model.bind_tools(tools)

    context_block = _build_context_block(finding, location, read_result, guidance, feedback)
    messages: list[Any] = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=context_block)]

    parsed: dict[str, Any] | None = None
    for _ in range(MAX_TOOL_ITERATIONS):
        response: AIMessage = await bound_model.ainvoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            parsed = _parse_patch_response(response.content)
            break

        for call in tool_calls:
            handler = tools_by_name.get(call["name"])
            if handler is None:
                output: Any = {"error": f"unknown tool {call['name']!r}"}
            else:
                try:
                    output = handler.invoke(call["args"])
                except Exception as exc:  # a tool failure must never crash the loop
                    output = {"error": str(exc)}
            messages.append(
                ToolMessage(content=json.dumps(output, default=str), tool_call_id=call["id"])
            )

    if parsed is None:
        raise LLMFixError(
            f"LLM did not propose a patch within {MAX_TOOL_ITERATIONS} tool-calling turns"
        )

    apply_edit(
        workspace,
        ledger,
        location["file"],
        old_string=parsed["old_string"],
        new_string=parsed["new_string"],
        replace_all=False,
    )

    return {
        "supported": True,
        "changed_files": [location["file"]],
        "old_version": None,
        "new_version": None,
        "fix_tier": "llm",
        "message": parsed.get("explanation", "LLM-generated patch"),
    }
