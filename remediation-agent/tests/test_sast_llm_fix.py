"""Tests for `sast.llm_fix.ask_llm_for_patch`'s tool-calling loop itself.

Every other test in this suite that touches the LLM-fallback path mocks
`ask_llm_for_patch` as a whole (a black box returning a canned FixResult) --
none of them exercise this module's own tool-binding, tool-execution, or
JSON-parsing logic. This file does, with a scripted fake chat model (no real
LLM call, no network) standing in for `BaseChatModel`.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from s17code.coding.edit import EditLedger

from remediation_agent.sast.llm_fix import LLMFixError, ask_llm_for_patch

REL_PATH = "src/Controllers/ProductController.cs"


class _ScriptedChatModel:
    """A minimal `BaseChatModel`-shaped fake: a fixed script of responses,
    popped one per `ainvoke` call. No real model, no network."""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self.bound_tools: list | None = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages):
        if not self._responses:
            raise AssertionError("chat model script exhausted -- more turns than expected")
        return self._responses.pop(0)


def _finding() -> dict:
    return {
        "id": "some.rule.not.in.the.template.registry",
        "title": "Insecure deserialization detected",
        "cwe_ids": ["CWE-502"],
        "file": REL_PATH,
        "line": 9,
        "snippet": "var model = JsonConvert.DeserializeObject<ProductModel>(data);",
    }


def _location() -> dict:
    return {
        "file": REL_PATH,
        "pattern_kind": "sast_line",
        "line": 9,
        "text": "            var model = JsonConvert.DeserializeObject<ProductModel>(data);",
    }


async def test_tool_loop_investigates_then_proposes_and_applies_patch(dotnet_sast_workspace):
    # Turn 1: the model calls a tool instead of answering immediately.
    tool_call_response = AIMessage(
        content="",
        tool_calls=[{"name": "grep", "args": {"pattern": "ProductModel"}, "id": "call_1"}],
    )
    # Turn 2: after seeing the tool's result, it answers with the patch.
    final_response = AIMessage(
        content=(
            '{"old_string": '
            '"            var model = JsonConvert.DeserializeObject<ProductModel>(data);", '
            '"new_string": '
            '"            var settings = new JsonSerializerSettings { TypeNameHandling = TypeNameHandling.None };'
            '\\n            var model = JsonConvert.DeserializeObject<ProductModel>(data, settings);", '
            '"explanation": "pinned TypeNameHandling to None"}'
        )
    )
    chat_model = _ScriptedChatModel([tool_call_response, final_response])
    ledger = EditLedger()

    result = await ask_llm_for_patch(
        chat_model, dotnet_sast_workspace, ledger, _finding(), _location(), guidance=None
    )

    assert result["supported"] is True
    assert result["fix_tier"] == "llm"
    assert result["changed_files"] == [REL_PATH]
    assert result["message"] == "pinned TypeNameHandling to None"
    # Confirms real tool objects (read_file/grep/glob/run) were actually
    # bound, not just that the loop "worked" some other way.
    assert chat_model.bound_tools is not None
    assert {t.name for t in chat_model.bound_tools} == {"read_file", "grep", "glob", "run"}

    final_text = dotnet_sast_workspace.resolve(REL_PATH).read_text(encoding="utf-8")
    assert "TypeNameHandling.None" in final_text


async def test_raises_llm_fix_error_when_loop_never_reaches_a_final_answer(dotnet_sast_workspace):
    # Every turn keeps calling a tool -- the model never stops to answer.
    responses = [
        AIMessage(content="", tool_calls=[{"name": "grep", "args": {"pattern": "x"}, "id": f"call_{i}"}])
        for i in range(10)
    ]
    chat_model = _ScriptedChatModel(responses)
    ledger = EditLedger()

    with pytest.raises(LLMFixError, match="tool-calling turns"):
        await ask_llm_for_patch(
            chat_model, dotnet_sast_workspace, ledger, _finding(), _location(), guidance=None
        )


async def test_raises_llm_fix_error_on_unparseable_final_response(dotnet_sast_workspace):
    chat_model = _ScriptedChatModel([AIMessage(content="I fixed it, trust me.")])
    ledger = EditLedger()

    with pytest.raises(LLMFixError):
        await ask_llm_for_patch(
            chat_model, dotnet_sast_workspace, ledger, _finding(), _location(), guidance=None
        )


async def test_feedback_and_guidance_included_in_prompt(dotnet_sast_workspace):
    captured: list = []

    class _CapturingChatModel(_ScriptedChatModel):
        async def ainvoke(self, messages):
            captured.append(messages)
            return await super().ainvoke(messages)

    final_response = AIMessage(
        content=(
            '{"old_string": '
            '"            var model = JsonConvert.DeserializeObject<ProductModel>(data);", '
            '"new_string": "fixed_call();", "explanation": "x"}'
        )
    )
    chat_model = _CapturingChatModel([final_response])
    ledger = EditLedger()

    await ask_llm_for_patch(
        chat_model,
        dotnet_sast_workspace,
        ledger,
        _finding(),
        _location(),
        guidance="Curated CWE-502 guidance text.",
        feedback="Your previous attempt failed the build gate.",
    )

    human_message_text = captured[0][1].content
    assert "Your previous attempt failed the build gate." in human_message_text
    assert "Curated CWE-502 guidance text." in human_message_text


async def test_read_file_tool_extends_the_edit_ledger(dotnet_sast_workspace):
    """A patch anchored on text read only via the `read_file` tool (not the
    initial context window) must still be accepted -- confirms the tool
    closures share the same EditLedger as the initial read, not a separate
    one that would make apply_edit's read-before-edit check fail.
    """
    # The .csproj is outside the initial window (which only reads around
    # the flagged line in ProductController.cs), so anchoring on it can only
    # work if the read_file tool call registered it in the same ledger.
    tool_call_response = AIMessage(
        content="",
        tool_calls=[{"name": "read_file", "args": {"relative_path": "sample.csproj"}, "id": "call_1"}],
    )
    final_response = AIMessage(
        content=(
            '{"old_string": "            var model = JsonConvert.DeserializeObject<ProductModel>(data);", '
            '"new_string": "fixed_call();", "explanation": "x"}'
        )
    )
    chat_model = _ScriptedChatModel([tool_call_response, final_response])
    ledger = EditLedger()

    result = await ask_llm_for_patch(
        chat_model, dotnet_sast_workspace, ledger, _finding(), _location(), guidance=None
    )
    assert result["supported"] is True
    assert "sample.csproj" in ledger.read
