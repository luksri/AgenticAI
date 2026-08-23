from __future__ import annotations

import pytest
from s17code.coding.edit import EditError, EditLedger

from remediation_agent.ecosystems.base import FixNotFoundError
from remediation_agent.ecosystems.dotnet import DotNetAdapter


def _finding(component: str = "Newtonsoft.Json", fixed_version: str | None = "13.0.3") -> dict:
    return {
        "id": "CVE-TEST-1",
        "severity": "HIGH",
        "category": "SCA",
        "file": "sample.csproj",
        "component": component,
        "fixed_version": fixed_version,
    }


def test_detect_true_on_fixture(dotnet_workspace):
    assert DotNetAdapter().detect(dotnet_workspace) is True


def test_detect_false_without_manifests(tmp_path):
    from s17code.coding.workspace import Workspace

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert DotNetAdapter().detect(Workspace.open(empty_dir)) is False


def test_locate_component_found(dotnet_workspace):
    locations = DotNetAdapter().locate_component(dotnet_workspace, _finding())
    assert len(locations) == 1
    location = locations[0]
    assert location["file"] == "sample.csproj"
    assert location["pattern_kind"] == "csproj_packagereference_selfclosing"
    assert location["old_version"] == "12.0.1"


def test_locate_component_not_present_returns_empty(dotnet_workspace):
    locations = DotNetAdapter().locate_component(dotnet_workspace, _finding(component="DoesNotExist"))
    assert locations == []


def test_locate_component_no_component_returns_empty(dotnet_workspace):
    finding = _finding()
    finding["component"] = None
    assert DotNetAdapter().locate_component(dotnet_workspace, finding) == []


def test_apply_version_fix_rewrites_file(dotnet_workspace):
    adapter = DotNetAdapter()
    ledger = EditLedger()
    finding = _finding()

    locations = adapter.locate_component(dotnet_workspace, finding)
    result = adapter.apply_version_fix(dotnet_workspace, ledger, finding, locations[0])

    assert result["changed_files"] == ["sample.csproj"]
    assert result["old_version"] == "12.0.1"
    assert result["new_version"] == "13.0.3"

    updated = dotnet_workspace.resolve("sample.csproj").read_text(encoding="utf-8")
    assert 'Version="13.0.3"' in updated
    assert 'Version="12.0.1"' not in updated
    # Include attribute untouched.
    assert 'Include="Newtonsoft.Json"' in updated


def test_apply_version_fix_raises_fix_not_found_when_anchor_incomplete(dotnet_workspace):
    adapter = DotNetAdapter()
    ledger = EditLedger()
    finding = _finding()
    bad_location = {"file": "sample.csproj", "pattern_kind": "csproj_packagereference_selfclosing"}

    with pytest.raises(FixNotFoundError):
        adapter.apply_version_fix(dotnet_workspace, ledger, finding, bad_location)


def test_apply_version_fix_raises_fix_not_found_without_fixed_version(dotnet_workspace):
    adapter = DotNetAdapter()
    ledger = EditLedger()
    finding = _finding(fixed_version=None)

    locations = adapter.locate_component(dotnet_workspace, _finding())
    with pytest.raises(FixNotFoundError):
        adapter.apply_version_fix(dotnet_workspace, ledger, finding, locations[0])


def test_apply_version_fix_already_at_target_version_is_not_an_error(dotnet_workspace):
    # A rerun of the same finding against a repo an earlier run already
    # fixed (or a component already released at the target version): the
    # component is already safe, so this must be a clean no-op result, not
    # FixNotFoundError. Verified against the exact scenario that surfaced
    # this -- old_version == fixed_version -- not just a synthetic case.
    adapter = DotNetAdapter()
    ledger = EditLedger()
    finding = _finding(fixed_version="12.0.1")  # matches the fixture's current version

    locations = adapter.locate_component(dotnet_workspace, finding)
    result = adapter.apply_version_fix(dotnet_workspace, ledger, finding, locations[0])

    assert result["changed_files"] == []
    assert result["already_satisfied"] is True
    assert result["old_version"] == result["new_version"] == "12.0.1"

    # The file itself must be untouched -- this is a report, not an edit.
    unchanged = dotnet_workspace.resolve("sample.csproj").read_text(encoding="utf-8")
    assert 'Version="12.0.1"' in unchanged


def test_apply_version_fix_ambiguous_anchor_raises_edit_error(dotnet_workspace):
    # Two identical PackageReference tags make the anchor non-unique, which
    # s17code.coding.edit.apply_edit refuses -- verify that failure mode is
    # the documented EditError, not something ad hoc.
    path = dotnet_workspace.resolve("sample.csproj")
    text = path.read_text(encoding="utf-8")
    duplicated = text.replace(
        '<PackageReference Include="Newtonsoft.Json" Version="12.0.1" />',
        '<PackageReference Include="Newtonsoft.Json" Version="12.0.1" />\n'
        '    <PackageReference Include="Newtonsoft.Json" Version="12.0.1" />',
    )
    path.write_text(duplicated, encoding="utf-8")

    adapter = DotNetAdapter()
    ledger = EditLedger()
    finding = _finding()
    locations = adapter.locate_component(dotnet_workspace, finding)
    assert len(locations) == 2  # both matched, anchor is identical text for both

    with pytest.raises(EditError):
        adapter.apply_version_fix(dotnet_workspace, ledger, finding, locations[0])


def test_build_and_test_command_none_when_gate_empty():
    adapter = DotNetAdapter()
    settings = {"gates": {"build": "", "test": ""}}
    assert adapter.build_command(settings) is None
    assert adapter.test_command(settings) is None


def test_build_command_splits_on_double_ampersand():
    adapter = DotNetAdapter()
    settings = {"gates": {"build": "dotnet restore && dotnet build", "test": "dotnet test"}}
    assert adapter.build_command(settings) == [["dotnet", "restore"], ["dotnet", "build"]]
    assert adapter.test_command(settings) == [["dotnet", "test"]]


def test_allowed_commands():
    assert DotNetAdapter().allowed_commands() == ("dotnet",)
