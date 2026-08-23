from __future__ import annotations

from s17code.coding.edit import EditLedger

from remediation_agent.strategies import sast as sast_strategy_module
from remediation_agent.strategies.base import StrategyContext
from remediation_agent.strategies.sast import SASTStrategy

RULE_ID = "csharp.lang.security.insecure-deserialization.insecure-deserialization"
REL_PATH = "src/Controllers/ProductController.cs"
VULNERABLE_LINE_NO = 9


def _finding(rule_id: str = RULE_ID) -> dict:
    return {
        "id": rule_id,
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


def _location(workspace) -> dict:
    text = workspace.resolve(REL_PATH).read_text(encoding="utf-8").splitlines()
    return {
        "file": REL_PATH,
        "pattern_kind": "sast_line",
        "line": VULNERABLE_LINE_NO,
        "text": text[VULNERABLE_LINE_NO - 1],
    }


def _unit(finding: dict) -> dict:
    return {
        "unit_id": "abc123",
        "category": "SAST",
        "component": None,
        "line": VULNERABLE_LINE_NO,
        "file": REL_PATH,
        "findings": [finding],
    }


async def test_template_path_used_for_known_rule_id(dotnet_sast_workspace):
    finding = _finding()
    ctx = StrategyContext(
        workspace=dotnet_sast_workspace,
        ledger=EditLedger(),
        adapter=None,
        unit=_unit(finding),
        locations=[_location(dotnet_sast_workspace)],
    )

    result = await SASTStrategy().remediate(ctx)

    assert result["supported"] is True
    assert result["fix_tier"] == "template"
    assert result["changed_files"] == [REL_PATH]

    updated = dotnet_sast_workspace.resolve(REL_PATH).read_text(encoding="utf-8")
    assert "TypeNameHandling.None" in updated


async def test_llm_fallback_used_for_unregistered_rule_id(monkeypatch, dotnet_sast_workspace):
    # Mock ask_llm_for_patch directly (rather than a real chat model / network
    # call) to confirm the LLM-fallback branch is actually reached when no
    # template claims the rule id, and that its result carries fix_tier=="llm".
    finding = _finding(rule_id="some.rule.not.in.the.template.registry")

    async def fake_ask_llm_for_patch(chat_model, workspace, ledger, finding, location, guidance, *, feedback=None):
        return {
            "supported": True,
            "changed_files": [location["file"]],
            "old_version": None,
            "new_version": None,
            "fix_tier": "llm",
            "message": "stubbed LLM patch",
        }

    monkeypatch.setattr(sast_strategy_module, "ask_llm_for_patch", fake_ask_llm_for_patch)
    # get_chat_model() would otherwise try to construct a real ChatAnthropic
    # client; since ask_llm_for_patch itself is stubbed above, the returned
    # object is never actually invoked.
    monkeypatch.setattr(sast_strategy_module, "get_chat_model", lambda: object())

    ctx = StrategyContext(
        workspace=dotnet_sast_workspace,
        ledger=EditLedger(),
        adapter=None,
        unit=_unit(finding),
        locations=[_location(dotnet_sast_workspace)],
    )

    result = await SASTStrategy().remediate(ctx)

    assert result["supported"] is True
    assert result["fix_tier"] == "llm"
    assert result["changed_files"] == [REL_PATH]
    assert "stubbed LLM patch" in result["message"]


async def test_llm_path_not_reached_when_template_applies(monkeypatch, dotnet_sast_workspace):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM fallback should not be reached when a template applies")

    monkeypatch.setattr(sast_strategy_module, "ask_llm_for_patch", fail_if_called)

    finding = _finding()
    ctx = StrategyContext(
        workspace=dotnet_sast_workspace,
        ledger=EditLedger(),
        adapter=None,
        unit=_unit(finding),
        locations=[_location(dotnet_sast_workspace)],
    )

    result = await SASTStrategy().remediate(ctx)

    assert result["fix_tier"] == "template"
