from __future__ import annotations

import pytest
from s17code.coding.edit import EditLedger

from remediation_agent.ecosystems.base import FixNotFoundError
from remediation_agent.ecosystems.java import JavaAdapter


def _maven_finding(component: str = "log4j-core", fixed_version: str | None = "2.17.1") -> dict:
    return {
        "id": "CVE-TEST-2",
        "severity": "CRITICAL",
        "category": "SCA",
        "file": "pom.xml",
        "component": component,
        "fixed_version": fixed_version,
    }


def _gradle_finding(
    component: str = "org.apache.logging.log4j:log4j-core", fixed_version: str | None = "2.17.1"
) -> dict:
    return {
        "id": "CVE-TEST-3",
        "severity": "CRITICAL",
        "category": "SCA",
        "file": "build.gradle",
        "component": component,
        "fixed_version": fixed_version,
    }


def test_detect_true_on_maven_fixture(java_workspace):
    assert JavaAdapter().detect(java_workspace) is True


def test_detect_true_on_gradle_fixture(java_gradle_workspace):
    assert JavaAdapter().detect(java_gradle_workspace) is True


def test_detect_false_without_manifests(tmp_path):
    from s17code.coding.workspace import Workspace

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert JavaAdapter().detect(Workspace.open(empty_dir)) is False


def test_locate_component_maven_by_artifact_id(java_workspace):
    locations = JavaAdapter().locate_component(java_workspace, _maven_finding(component="log4j-core"))
    assert len(locations) == 1
    location = locations[0]
    assert location["file"] == "pom.xml"
    assert location["pattern_kind"] == "pom_dependency"
    assert location["old_version"] == "2.14.0"
    assert "<artifactId>log4j-core</artifactId>" in location["anchor"]
    assert "<version>2.14.0</version>" in location["anchor"]


def test_locate_component_maven_by_group_and_artifact_id(java_workspace):
    locations = JavaAdapter().locate_component(
        java_workspace, _maven_finding(component="org.apache.logging.log4j:log4j-core")
    )
    assert len(locations) == 1
    assert locations[0]["old_version"] == "2.14.0"


def test_locate_component_maven_not_present_returns_empty(java_workspace):
    locations = JavaAdapter().locate_component(java_workspace, _maven_finding(component="does-not-exist"))
    assert locations == []


def test_apply_version_fix_maven_already_at_target_version_is_not_an_error(java_workspace):
    adapter = JavaAdapter()
    ledger = EditLedger()
    finding = _maven_finding(fixed_version="2.14.0")  # matches the fixture's current version

    locations = adapter.locate_component(java_workspace, finding)
    result = adapter.apply_version_fix(java_workspace, ledger, finding, locations[0])

    assert result["changed_files"] == []
    assert result["already_satisfied"] is True

    unchanged = java_workspace.resolve("pom.xml").read_text(encoding="utf-8")
    assert "<version>2.14.0</version>" in unchanged


def test_apply_version_fix_maven_rewrites_file(java_workspace):
    adapter = JavaAdapter()
    ledger = EditLedger()
    finding = _maven_finding()

    locations = adapter.locate_component(java_workspace, finding)
    result = adapter.apply_version_fix(java_workspace, ledger, finding, locations[0])

    assert result["changed_files"] == ["pom.xml"]
    assert result["old_version"] == "2.14.0"
    assert result["new_version"] == "2.17.1"

    updated = java_workspace.resolve("pom.xml").read_text(encoding="utf-8")
    assert "<version>2.17.1</version>" in updated
    assert "<version>2.14.0</version>" not in updated
    # Sibling artifactId untouched, and the project's own top-level <version>
    # (1.0.0, outside the <dependency> block) must not have been touched.
    assert "<artifactId>log4j-core</artifactId>" in updated
    assert "<version>1.0.0</version>" in updated


def test_apply_version_fix_maven_raises_without_fixed_version(java_workspace):
    adapter = JavaAdapter()
    ledger = EditLedger()
    locations = adapter.locate_component(java_workspace, _maven_finding())
    finding = _maven_finding(fixed_version=None)

    with pytest.raises(FixNotFoundError):
        adapter.apply_version_fix(java_workspace, ledger, finding, locations[0])


def test_locate_component_gradle_literal_version(java_gradle_workspace):
    locations = JavaAdapter().locate_component(java_gradle_workspace, _gradle_finding())
    assert len(locations) == 1
    location = locations[0]
    assert location["file"] == "build.gradle"
    assert location["pattern_kind"] == "gradle_dependency"
    assert location["old_version"] == "2.14.0"


def test_locate_component_gradle_version_catalog_only_returns_empty(java_gradle_workspace):
    # No literal "group:artifact:version" string exists for this component in
    # the build file -- must not guess, must return no locations.
    locations = JavaAdapter().locate_component(
        java_gradle_workspace, _gradle_finding(component="com.example:not-declared")
    )
    assert locations == []


def test_apply_version_fix_gradle_rewrites_file(java_gradle_workspace):
    adapter = JavaAdapter()
    ledger = EditLedger()
    finding = _gradle_finding()

    locations = adapter.locate_component(java_gradle_workspace, finding)
    result = adapter.apply_version_fix(java_gradle_workspace, ledger, finding, locations[0])

    assert result["old_version"] == "2.14.0"
    assert result["new_version"] == "2.17.1"

    updated = java_gradle_workspace.resolve("build.gradle").read_text(encoding="utf-8")
    assert "org.apache.logging.log4j:log4j-core:2.17.1" in updated
    assert "org.apache.logging.log4j:log4j-core:2.14.0" not in updated
    # Unrelated dependency untouched.
    assert "junit:junit:4.13.1" in updated


def test_build_and_test_command_none_when_gate_empty():
    adapter = JavaAdapter()
    settings = {"gates": {"build": "", "test": ""}}
    assert adapter.build_command(settings) is None
    assert adapter.test_command(settings) is None


def test_build_command_splits_on_double_ampersand():
    adapter = JavaAdapter()
    settings = {"gates": {"build": "mvn -B clean && mvn -B package"}}
    assert adapter.build_command(settings) == [
        ["mvn", "-B", "clean"],
        ["mvn", "-B", "package"],
    ]


def test_allowed_commands():
    assert JavaAdapter().allowed_commands() == ("mvn", "gradle", "gradlew", "java")
