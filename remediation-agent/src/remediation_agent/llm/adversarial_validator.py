"""A validator that is a different agent, with a different job and no hands.

Standalone reimplementation of the *pattern* in session-17's
`s17code/coding/validate.py` (read, not imported: that module is tightly
coupled to session-17's own LLM gateway plumbing, which this project
deliberately does not reuse -- see `llm/provider.py`).

Three things make this validation run separate from the run that produced the
fix, same as session-17's version:

**A fresh context.** This function is invoked with only a diff and a
requirement string -- never the conversation that produced the fix -- so it
cannot inherit the fix-generation strategy's assumptions about what
"obviously works".

**A hostile brief.** `VALIDATOR_SYSTEM` asks the model to find what is
broken, not to confirm the fix is fine.

**No hands.** The validator gets read-only tools (`read_code`, `grep_code`,
`run_command`) bound via LangChain tool-calling. `apply_edit`/`create_file`
are never exposed here.

This whole module is only ever invoked when
`get_settings().enable_adversarial_validation` is true (default false); the
default remediation path never imports or touches it beyond this module's
own top-level imports, which are themselves cheap (no optional SDK import
happens here -- the caller already resolved a chat model via
`llm.provider.get_chat_model()` before calling `validate_fix`).
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from s17code.coding.edit import EditLedger, read_code
from s17code.coding.exec import CommandError, run_command
from s17code.coding.search import grep_code
from s17code.coding.workspace import Workspace

VALIDATOR_SYSTEM = (
    "You are a validation agent. A code fix has just been generated and "
    "somebody believes it works. Your job is to find out where that belief "
    "is wrong.\n\n"
    "You may read files, search them, and run commands. You may NOT edit "
    "anything: you report, you do not repair.\n\n"
    "Do not accept that a diff exists as evidence that the fix works. Run "
    "it: read the changed files in full, search for anything the diff might "
    "have broken elsewhere in the repo, and execute whatever commands are "
    "available and relevant (build/test/lint) to prove the fix holds, not "
    "merely to eyeball the patch text.\n\n"
    "Write whatever exploratory commands you need in order to prove a "
    "defect. A defect you have not reproduced by actually running something "
    "is a guess, and you must label it as such (reproduced: false).\n\n"
    "Return JSON only, no prose outside the JSON object:\n"
    '{"passed": bool, "findings": [{"what": str, "evidence": str, '
    '"reproduced": bool, "severity": "blocker"|"major"|"minor"}], '
    '"summary": str}\n'
    "An empty findings list means you executed something and the fix "
    "genuinely held. Saying so without having run anything is the one "
    "failure that matters here."
)

MAX_TOOL_ITERATIONS = 8


async def validate_fix(
    chat_model: BaseChatModel, workspace: Workspace, diff: str, requirement: str
) -> dict[str, Any]:
    """Send a diff + requirement to `chat_model` with read-only tool access.

    Returns the parsed `{"passed", "findings", "summary"}` shape described in
    VALIDATOR_SYSTEM. Never raises for a malformed model response -- a
    non-JSON or absent verdict is folded into a failing result instead, since
    this function's caller (`validate_build_test`) treats any exception from
    the *caller's* perspective as non-fatal, but a clean dict return here
    keeps that caller's error handling simple.
    """
    ledger = EditLedger()

    @tool
    def read_file(relative_path: str, offset: int = 1, limit: int | None = None) -> dict:
        """Read part of a file in the workspace (ranged by line, 1-indexed)."""
        return read_code(workspace, ledger, relative_path, offset=offset, limit=limit)

    @tool
    def grep(pattern: str, path_glob: str = "*", limit: int = 60, ignore_case: bool = False) -> dict:
        """Search file contents in the workspace for a regex pattern."""
        return grep_code(workspace, pattern, path_glob=path_glob, limit=limit, ignore_case=ignore_case)

    @tool
    def run(command: list[str], timeout: int = 120) -> dict:
        """Run one allowlisted, no-shell command inside the workspace and return its result."""
        try:
            result = run_command(workspace, command, timeout=timeout)
        except CommandError as exc:
            return {"error": str(exc)}
        return result.as_dict()

    tools = [read_file, grep, run]
    tools_by_name = {t.name: t for t in tools}
    bound_model = chat_model.bind_tools(tools)

    goal = (
        "Validate that this requirement is genuinely met by the change "
        f"below.\n\nRequirement:\n{requirement}\n\nDiff:\n{diff}\n\n"
        "Run it. Report what is broken."
    )
    messages: list[Any] = [SystemMessage(content=VALIDATOR_SYSTEM), HumanMessage(content=goal)]

    for _ in range(MAX_TOOL_ITERATIONS):
        response: AIMessage = await bound_model.ainvoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            return _parse_verdict(response.content)

        for call in tool_calls:
            handler = tools_by_name.get(call["name"])
            if handler is None:
                output: Any = {"error": f"unknown tool {call['name']!r}"}
            else:
                try:
                    output = handler.invoke(call["args"])
                except Exception as exc:  # tool execution must never crash the validator loop
                    output = {"error": str(exc)}
            messages.append(
                ToolMessage(content=json.dumps(output, default=str), tool_call_id=call["id"])
            )

    return {
        "passed": False,
        "findings": [
            {
                "what": "validator exceeded its tool-call budget without reaching a verdict",
                "evidence": f"stopped after {MAX_TOOL_ITERATIONS} tool-calling turns",
                "reproduced": False,
                "severity": "major",
            }
        ],
        "summary": "adversarial validator did not converge to a JSON verdict",
    }


def _parse_verdict(content: Any) -> dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        parsed = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {
            "passed": False,
            "findings": [
                {
                    "what": "validator did not return parseable JSON",
                    "evidence": text[:500],
                    "reproduced": False,
                    "severity": "major",
                }
            ],
            "summary": "could not parse validator output",
        }
    parsed.setdefault("passed", False)
    parsed.setdefault("findings", [])
    parsed.setdefault("summary", "")
    return parsed


def summarise(result: dict[str, Any]) -> dict[str, Any]:
    """Flatten a validator run into something a graph node can act on.

    Matches session-17's `s17code/coding/validate.py::summarise` shape.
    """
    findings = result.get("findings") or []
    blockers = [f for f in findings if f.get("severity") == "blocker"]
    return {
        "passed": bool(result.get("passed")) and not blockers,
        "blockers": len(blockers),
        "findings": findings,
        "summary": result.get("summary", ""),
        "reproduced_any": any(f.get("reproduced") for f in findings),
    }
