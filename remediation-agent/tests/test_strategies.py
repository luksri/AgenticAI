from __future__ import annotations

from s17code.coding.edit import EditLedger

from remediation_agent.ecosystems.dotnet import DotNetAdapter
from remediation_agent.strategies.base import StrategyContext
from remediation_agent.strategies.registry import get as get_strategy
from remediation_agent.strategies.sca import SCAStrategy
from remediation_agent.strategies.unsupported import UnsupportedStrategy


def _unit(findings) -> dict:
    return {
        "unit_id": "abc123def456",
        "category": "SCA",
        "component": "Newtonsoft.Json",
        "file": "sample.csproj",
        "findings": findings,
    }


def test_registry_returns_sca_strategy_for_sca_category():
    strategy = get_strategy("SCA")
    assert isinstance(strategy, SCAStrategy)


def test_registry_falls_back_to_unsupported_for_unknown_category():
    # "SAST" is no longer a stand-in for "unrecognized category" now that
    # SASTStrategy is registered (see strategies/sast.py) -- use a category
    # that genuinely has no registered strategy instead.
    strategy = get_strategy("SECRETS")
    assert isinstance(strategy, UnsupportedStrategy)


def test_unsupported_strategy_touches_nothing(dotnet_workspace):
    ledger = EditLedger()
    adapter = DotNetAdapter()
    unit = _unit([{"id": "CVE-1", "category": "SECRETS", "file": "sample.csproj"}])
    unit["category"] = "SECRETS"
    ctx = StrategyContext(workspace=dotnet_workspace, ledger=ledger, adapter=adapter, unit=unit, locations=[])

    result = get_strategy("SECRETS").remediate(ctx)

    assert result == {
        "supported": False,
        "changed_files": [],
        "old_version": None,
        "new_version": None,
        "message": "category 'SECRETS' not yet supported",
    }
    assert dotnet_workspace.changed_files() == []


def test_sca_strategy_applies_version_fix(dotnet_workspace):
    ledger = EditLedger()
    adapter = DotNetAdapter()
    finding = {
        "id": "CVE-1",
        "severity": "HIGH",
        "category": "SCA",
        "file": "sample.csproj",
        "component": "Newtonsoft.Json",
        "fixed_version": "13.0.3",
    }
    locations = adapter.locate_component(dotnet_workspace, finding)
    unit = _unit([finding])
    ctx = StrategyContext(
        workspace=dotnet_workspace, ledger=ledger, adapter=adapter, unit=unit, locations=locations
    )

    result = SCAStrategy().remediate(ctx)

    assert result["supported"] is True
    assert result["changed_files"] == ["sample.csproj"]
    assert result["old_version"] == "12.0.1"
    assert result["new_version"] == "13.0.3"


def test_sca_strategy_already_satisfied_reports_no_op_not_failure(dotnet_workspace):
    # A rerun of the same finding against a repo an earlier run already
    # fixed -- the strategy layer must propagate the adapter's
    # already_satisfied signal, not just the raw changed_files list, so
    # generate_fix.py/decide.py downstream can tell "nothing to do" apart
    # from "something went wrong."
    ledger = EditLedger()
    adapter = DotNetAdapter()
    finding = {
        "id": "CVE-1",
        "severity": "HIGH",
        "category": "SCA",
        "file": "sample.csproj",
        "component": "Newtonsoft.Json",
        "fixed_version": "12.0.1",  # matches the fixture's current version
    }
    locations = adapter.locate_component(dotnet_workspace, finding)
    unit = _unit([finding])
    ctx = StrategyContext(
        workspace=dotnet_workspace, ledger=ledger, adapter=adapter, unit=unit, locations=locations
    )

    result = SCAStrategy().remediate(ctx)

    assert result["supported"] is True
    assert result["changed_files"] == []
    assert result["already_satisfied"] is True


def test_sca_strategy_picks_highest_version_on_disagreement(dotnet_workspace):
    ledger = EditLedger()
    adapter = DotNetAdapter()
    finding_low = {
        "id": "CVE-low",
        "severity": "HIGH",
        "category": "SCA",
        "file": "sample.csproj",
        "component": "Newtonsoft.Json",
        "fixed_version": "12.0.3",
    }
    finding_high = {
        "id": "CVE-high",
        "severity": "CRITICAL",
        "category": "SCA",
        "file": "sample.csproj",
        "component": "Newtonsoft.Json",
        "fixed_version": "13.0.3",
    }
    locations = adapter.locate_component(dotnet_workspace, finding_low)
    unit = _unit([finding_low, finding_high])
    ctx = StrategyContext(
        workspace=dotnet_workspace, ledger=ledger, adapter=adapter, unit=unit, locations=locations
    )

    result = SCAStrategy().remediate(ctx)

    assert result["new_version"] == "13.0.3"
    assert "chose the highest" in result["message"]
    assert "CVE-high" in result["message"]
