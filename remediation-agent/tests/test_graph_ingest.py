"""Tests for the `ingest` node directly (not via the compiled graph, so
these run without any of the other-agent-owned modules existing)."""
from __future__ import annotations

import subprocess

import pytest

from remediation_agent.graph.nodes.ingest import ingest


def _init_git_repo(path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _init_git_repo(tmp_path)
    return tmp_path


VALID_PAYLOAD_TEMPLATE = {
    "run_context": {
        "correlation_id": "abc123",
        "pipeline_id": "456789",
        "project_id": "12345",
        "commit_sha": "a1b2c3",
    },
    "source": {"mode": "workspace", "path": None, "scope": "full"},
    "settings": {
        "severity": ["HIGH", "CRITICAL"],
        "scope": {"allow": [], "deny": []},
        "gates": {"build": "", "test": ""},
    },
    "findings": [
        {
            "id": "CVE-2024-12345",
            "severity": "HIGH",
            "category": "SCA",
            "file": "package.json",
            "component": "express",
            "fixed_version": "4.18.0",
        }
    ],
}


@pytest.mark.asyncio
async def test_ingest_valid_payload_produces_expected_state(repo):
    payload = {**VALID_PAYLOAD_TEMPLATE, "source": {**VALID_PAYLOAD_TEMPLATE["source"], "path": str(repo)}}

    result = await ingest(payload)

    assert result["ingest_error"] is None
    assert result["workspace_root"] == str(repo)
    assert result["run_context"]["project_id"] == "12345"
    assert result["settings"]["severity"] == ["HIGH", "CRITICAL"]
    assert len(result["findings"]) == 1
    assert result["findings"][0]["id"] == "CVE-2024-12345"


@pytest.mark.asyncio
async def test_ingest_invalid_payload_sets_ingest_error_without_raising():
    # Missing required fields (run_context, source) entirely.
    result = await ingest({"findings": []})

    assert "ingest_error" in result
    assert result["ingest_error"]


@pytest.mark.asyncio
async def test_ingest_unusable_workspace_sets_ingest_error(tmp_path):
    # A valid payload shape, but source.path points at something that is not
    # a directory / not a workspace Workspace.open() can use.
    missing_path = str(tmp_path / "does-not-exist")
    payload = {**VALID_PAYLOAD_TEMPLATE, "source": {**VALID_PAYLOAD_TEMPLATE["source"], "path": missing_path}}

    result = await ingest(payload)

    assert result["ingest_error"]
