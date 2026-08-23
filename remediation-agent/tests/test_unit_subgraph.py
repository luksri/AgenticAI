"""Tests for the per-unit subgraph's routing guarantee: once a node sets a
terminal `decision`, every later node in the chain is skipped and control
goes straight to `decide`.

Importing `remediation_agent.graph.unit_subgraph` pulls in every node under
`graph/nodes/unit/*.py`, which import from `remediation_agent.ecosystems.*`,
`remediation_agent.strategies.*`, and `remediation_agent.scope` -- all owned
by a second agent building in parallel. If those modules don't exist yet in
this environment, this whole file will fail to collect; that's expected and
not a bug in this test, per the project brief ("best-effort... don't block
on this").
"""
from __future__ import annotations

import subprocess

import pytest

unit_subgraph = pytest.importorskip("remediation_agent.graph.unit_subgraph")


def _init_git_repo(path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _init_git_repo(tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_preset_decision_skips_straight_to_decide(repo):
    """A decision already present in the initial state (as if an earlier
    node -- outside this subgraph invocation -- had already decided the
    unit is done) must survive through `classify_ecosystem` (the mandatory
    entry point) and cause every conditional route from then on to jump to
    `decide`, never reaching `locate`/`generate_fix`/`guard_check`/
    `validate_build_test`.
    """
    initial_state = {
        "unit": {
            "unit_id": "unit-preset",
            "category": "SCA",
            "component": "express",
            "file": "package.json",
            "findings": [],
        },
        "run_context": {"correlation_id": "c1", "project_id": "p1", "commit_sha": "sha1"},
        "settings": {"scope": {"allow": [], "deny": []}, "gates": {"build": "", "test": ""}},
        "workspace_root": str(repo),
        "decision": "unsupported_ecosystem",
        "error": "preset for routing test",
    }

    result = await unit_subgraph.UNIT_GRAPH.ainvoke(initial_state)

    # decide() sees an already-set decision and returns {} unchanged, so the
    # preset decision (or an equivalent one classify_ecosystem itself may
    # have independently reached, e.g. because this bare repo also isn't a
    # recognized ecosystem) must be the final terminal decision.
    assert result["decision"] == "unsupported_ecosystem"

    # None of the skipped nodes' outputs should be present: they never ran.
    assert result.get("locations") is None
    assert result.get("fix_result") is None
    assert result.get("guard_result") is None
    assert result.get("build_result") is None
    assert result.get("test_result") is None

    # decide() must not have branched/committed for a non-passing decision.
    assert result.get("branch") is None
    assert result.get("commit_sha") is None


@pytest.mark.asyncio
async def test_already_satisfied_fix_passes_without_creating_a_branch(dotnet_workspace):
    """A finding whose fixed_version the repo is already at (e.g. a rerun
    against a repo an earlier run already fixed) must report `pass` -- not
    `fix_failed` -- and must not create a branch or commit at all, since
    there's nothing to put on one. Runs the real subgraph end to end against
    the real .NET fixture, not a mocked strategy, since this is exactly the
    scenario a user hit by rerunning `run-once` against an already-fixed
    demo checkout.
    """
    starting_branch = dotnet_workspace.current_branch()

    initial_state = {
        "unit": {
            "unit_id": "already-satisfied-test",
            "category": "SCA",
            "component": "Newtonsoft.Json",
            "line": None,
            "file": "sample.csproj",
            "findings": [
                {
                    "id": "CVE-TEST",
                    "severity": "HIGH",
                    "category": "SCA",
                    "file": "sample.csproj",
                    "component": "Newtonsoft.Json",
                    "fixed_version": "12.0.1",  # matches the fixture's current version
                }
            ],
        },
        "run_context": {"correlation_id": "c1", "project_id": "p1", "commit_sha": "sha1"},
        "settings": {"scope": {"allow": [], "deny": []}, "gates": {"build": "", "test": ""}},
        "workspace_root": str(dotnet_workspace.root),
    }

    result = await unit_subgraph.UNIT_GRAPH.ainvoke(initial_state)

    assert result["decision"] == "pass"
    assert result.get("branch") is None
    assert result.get("commit_sha") is None
    assert result["fix_result"]["already_satisfied"] is True

    # The workspace must never have been branched off of -- decide.py's
    # already_satisfied short-circuit runs before workspace.branch() at all.
    assert dotnet_workspace.current_branch() == starting_branch
