"""Integration test for the LLM-authored-SAST-fix retry loop.

Runs the real `UNIT_GRAPH` end to end (not mocking around guard_check/
validate_build_test/routing, and not mocking `ask_llm_for_patch`'s own
internals -- the fakes below stand in for a chat model's *decision*, not for
this project's own code). Exercises the whole loop this session added:
`validate_build_test.py` requesting a retry, `unit_subgraph.py`'s
`_route_with_retry` looping back to `generate_fix`, `_retry.py`'s budget
check, and `generate_fix.py` threading `state["validation_feedback"]` into
`StrategyContext.feedback`.

`run_semgrep_verify` and the adversarial validator are mocked here, not the
real binary/a real chat model: this file's job is verifying the *loop*
(routing, state, budget, feedback content), which doesn't need a real
scanner or LLM to exercise correctly, and depending on a real Semgrep
registry rule resolving over the network would make this test both slow and
flaky. `semgrep_verify.py`'s own correctness (including the "zero rules
loaded" fail-closed case this project's real sample rule id turned out to
hit) is covered directly in test_sast_semgrep_verify.py instead.
"""
from __future__ import annotations

from s17code.coding.edit import apply_edit, read_code

from remediation_agent.graph.unit_subgraph import UNIT_GRAPH
from remediation_agent.llm import adversarial_validator as adversarial_validator_module
from remediation_agent.llm import provider as llm_provider_module
from remediation_agent.strategies import sast as sast_strategy_module

RULE_ID = "csharp.lang.security.insecure-deserialization.insecure-deserialization"
REL_PATH = "src/Controllers/ProductController.cs"
VULNERABLE_LINE_NO = 9


def _finding() -> dict:
    return {
        "id": "some.rule.not.in.the.template.registry",  # forces the LLM tier
        "tool": "semgrep",
        "category": "SAST",
        "lane": "code",
        "file": REL_PATH,
        "severity": "HIGH",
        "title": "Insecure deserialization detected",
        "line": VULNERABLE_LINE_NO,
        "snippet": "var model = JsonConvert.DeserializeObject<ProductModel>(data);",
        "cwe_ids": ["CWE-502"],
        "correlated": True,
    }


def _unit_state(dotnet_sast_workspace, unit_id: str) -> dict:
    return {
        "unit": {
            "unit_id": unit_id,
            "category": "SAST",
            "component": None,
            "line": VULNERABLE_LINE_NO,
            "file": REL_PATH,
            "findings": [_finding()],
        },
        "run_context": {"project_id": "p", "commit_sha": "c"},
        "settings": {"gates": {"build": "", "test": ""}, "scope": {"allow": [], "deny": []}},
        "workspace_root": str(dotnet_sast_workspace.root),
    }


def _mock_always_passing_adversarial(monkeypatch):
    """The mandatory adversarial gate (fix_tier == 'llm') would otherwise
    need a real ANTHROPIC_API_KEY. Mocking it lets these tests isolate the
    retry loop itself from that separate dependency."""
    monkeypatch.setattr(llm_provider_module, "get_chat_model", lambda: object())

    async def fake_validate_fix(chat_model, workspace, diff, requirement):
        return {"passed": True, "findings": [], "summary": "ok"}

    monkeypatch.setattr(adversarial_validator_module, "validate_fix", fake_validate_fix)


async def test_retry_loop_recovers_after_gate_rejects_first_attempt(dotnet_sast_workspace, monkeypatch):
    attempts: list[str | None] = []

    async def fake_ask_llm_for_patch(chat_model, workspace, ledger, finding, location, guidance, *, feedback=None):
        attempts.append(feedback)
        read_code(workspace, ledger, location["file"], offset=max(1, location["line"] - 2), limit=5)
        old = location["text"]
        new = old + f"  // attempt {len(attempts)}"
        apply_edit(workspace, ledger, location["file"], old_string=old, new_string=new, replace_all=False)
        return {
            "supported": True,
            "changed_files": [location["file"]],
            "old_version": None,
            "new_version": None,
            "fix_tier": "llm",
            "message": f"attempt {len(attempts)}",
        }

    semgrep_calls = {"count": 0}

    async def fake_run_semgrep_verify(workspace, finding, settings):
        semgrep_calls["count"] += 1
        if semgrep_calls["count"] == 1:
            return {"passed": False, "raw": {}, "error": None}
        return {"passed": True, "raw": {}, "error": None}

    monkeypatch.setattr(sast_strategy_module, "ask_llm_for_patch", fake_ask_llm_for_patch)
    monkeypatch.setattr(sast_strategy_module, "get_chat_model", lambda: object())
    monkeypatch.setattr(
        "remediation_agent.sast.semgrep_verify.run_semgrep_verify", fake_run_semgrep_verify
    )
    _mock_always_passing_adversarial(monkeypatch)

    result = await UNIT_GRAPH.ainvoke(_unit_state(dotnet_sast_workspace, "retrytest"))

    assert len(attempts) == 2, f"expected exactly 2 ask_llm_for_patch calls, got {len(attempts)}"
    assert attempts[0] is None, "first attempt should carry no feedback"
    assert attempts[1] is not None and "semgrep" in attempts[1].lower(), (
        "second attempt should carry feedback naming the semgrep re-verification failure"
    )

    assert result["decision"] == "pass"
    assert result["retry_count"] == 1
    assert result.get("branch") and result.get("commit_sha")

    final_text = dotnet_sast_workspace.resolve(REL_PATH).read_text(encoding="utf-8")
    assert "attempt 2" in final_text
    assert "attempt 1" not in final_text  # attempt 1's edit was rolled back, not layered on top


async def test_retry_budget_exhausted_reports_terminal_failure(dotnet_sast_workspace, monkeypatch):
    """Every attempt is rejected by the same gate -- confirms the loop
    terminates (does not run forever) and reports a clean terminal decision
    once `sast_max_attempts` is used up, rather than looping past it or
    crashing.
    """
    attempts: list[str | None] = []

    async def always_insufficient(chat_model, workspace, ledger, finding, location, guidance, *, feedback=None):
        attempts.append(feedback)
        read_code(workspace, ledger, location["file"], offset=max(1, location["line"] - 2), limit=5)
        old = location["text"]
        new = old + f"  // attempt {len(attempts)}"
        apply_edit(workspace, ledger, location["file"], old_string=old, new_string=new, replace_all=False)
        return {
            "supported": True,
            "changed_files": [location["file"]],
            "old_version": None,
            "new_version": None,
            "fix_tier": "llm",
            "message": f"attempt {len(attempts)}: still insufficient",
        }

    async def always_failing_semgrep(workspace, finding, settings):
        return {"passed": False, "raw": {}, "error": None}

    monkeypatch.setattr(sast_strategy_module, "ask_llm_for_patch", always_insufficient)
    monkeypatch.setattr(sast_strategy_module, "get_chat_model", lambda: object())
    monkeypatch.setattr(
        "remediation_agent.sast.semgrep_verify.run_semgrep_verify", always_failing_semgrep
    )
    _mock_always_passing_adversarial(monkeypatch)

    from remediation_agent.config import get_settings

    result = await UNIT_GRAPH.ainvoke(_unit_state(dotnet_sast_workspace, "retrytest2"))

    assert len(attempts) == get_settings().sast_max_attempts
    assert result["decision"] == "fix_failed_validation"
    assert "semgrep" in result["error"].lower()

    # The workspace must be left clean, not carrying the last failed attempt.
    final_text = dotnet_sast_workspace.resolve(REL_PATH).read_text(encoding="utf-8")
    assert "// attempt" not in final_text


async def test_no_retry_for_template_tier_fix(dotnet_sast_workspace, monkeypatch):
    """A deterministic template fix that a gate rejects must NOT be retried
    -- see _retry.py's docstring for why (retrying it would just reproduce
    the identical, already-known-bad output).
    """
    finding = {
        "id": RULE_ID,  # this one IS in the template registry
        "tool": "semgrep",
        "category": "SAST",
        "file": REL_PATH,
        "severity": "HIGH",
        "line": VULNERABLE_LINE_NO,
        "snippet": "var model = JsonConvert.DeserializeObject<ProductModel>(data);",
        "cwe_ids": ["CWE-502"],
    }
    unit_state = _unit_state(dotnet_sast_workspace, "retrytest3")
    unit_state["unit"]["findings"] = [finding]

    semgrep_calls = {"count": 0}

    async def always_failing_semgrep(workspace, finding, settings):
        semgrep_calls["count"] += 1
        return {"passed": False, "raw": {}, "error": None}

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("ask_llm_for_patch should not be reached for a template-tier fix")

    monkeypatch.setattr(sast_strategy_module, "ask_llm_for_patch", fail_if_called)
    monkeypatch.setattr(
        "remediation_agent.sast.semgrep_verify.run_semgrep_verify", always_failing_semgrep
    )

    result = await UNIT_GRAPH.ainvoke(unit_state)

    assert semgrep_calls["count"] == 1, "a template-tier failure must not retry"
    assert result["decision"] == "fix_failed_validation"
    assert result.get("retry_count") is None
