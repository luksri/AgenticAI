from __future__ import annotations

import shutil

import pytest
from s17code.coding.exec import CommandError

from remediation_agent.sast import semgrep_verify as semgrep_verify_module
from remediation_agent.sast.semgrep_verify import run_semgrep_verify

RULE_ID = "csharp.lang.security.insecure-deserialization.insecure-deserialization"


def _finding() -> dict:
    return {
        "id": RULE_ID,
        "file": "src/Controllers/ProductController.cs",
    }


@pytest.mark.asyncio
async def test_passes_cleanly_when_semgrep_not_installed(monkeypatch, dotnet_sast_workspace):
    # Simulates the real possibility that `semgrep` isn't on PATH in whatever
    # environment runs this: s17code.coding.exec.run_command raises
    # CommandError before anything runs. run_semgrep_verify must report this
    # cleanly, never raise.
    def fake_run_command(workspace, command, timeout=120):
        raise CommandError("command not found: semgrep")

    monkeypatch.setattr(semgrep_verify_module, "run_command", fake_run_command)

    result = await run_semgrep_verify(dotnet_sast_workspace, _finding(), settings={})

    assert result == {
        "passed": False,
        "raw": {},
        "error": "semgrep could not be run: command not found: semgrep",
    }


@pytest.mark.asyncio
async def test_passes_when_results_list_is_empty(monkeypatch, dotnet_sast_workspace):
    # `paths.scanned` non-empty is what makes an empty `results` list mean
    # "genuinely scanned and found nothing" rather than "0 rules loaded" --
    # see test_fails_closed_when_zero_files_scanned below for the latter.
    class _FakeResult:
        stdout = '{"results": [], "errors": [], "paths": {"scanned": ["src/Controllers/ProductController.cs"]}}'
        stderr = ""
        timed_out = False

    def fake_run_command(workspace, command, timeout=120):
        return _FakeResult()

    monkeypatch.setattr(semgrep_verify_module, "run_command", fake_run_command)

    result = await run_semgrep_verify(dotnet_sast_workspace, _finding(), settings={})

    assert result["passed"] is True
    assert result["error"] is None


@pytest.mark.asyncio
async def test_fails_closed_when_zero_files_scanned(monkeypatch, dotnet_sast_workspace):
    # Discovered against the real semgrep binary: `--config r/<rule-id>` for
    # a rule id that doesn't resolve to any real public-registry rule loads
    # ZERO rules and exits 0 with an empty `results` list and an empty
    # `paths.scanned` list -- indistinguishable from "genuinely fixed" by
    # `results` alone. This must fail closed, not silently report "passed".
    class _FakeResult:
        stdout = '{"results": [], "errors": [], "paths": {"scanned": []}}'
        stderr = ""
        timed_out = False

    def fake_run_command(workspace, command, timeout=120):
        return _FakeResult()

    monkeypatch.setattr(semgrep_verify_module, "run_command", fake_run_command)

    result = await run_semgrep_verify(dotnet_sast_workspace, _finding(), settings={})

    assert result["passed"] is False
    assert result["error"] is not None
    assert "zero files" in result["error"]


@pytest.mark.asyncio
async def test_fails_when_rule_still_fires(monkeypatch, dotnet_sast_workspace):
    class _FakeResult:
        stdout = f'{{"results": [{{"check_id": "{RULE_ID}"}}], "errors": []}}'
        stderr = ""
        timed_out = False

    def fake_run_command(workspace, command, timeout=120):
        return _FakeResult()

    monkeypatch.setattr(semgrep_verify_module, "run_command", fake_run_command)

    result = await run_semgrep_verify(dotnet_sast_workspace, _finding(), settings={})

    assert result["passed"] is False
    assert result["error"] is None


@pytest.mark.asyncio
async def test_handles_unparseable_json_cleanly(monkeypatch, dotnet_sast_workspace):
    class _FakeResult:
        stdout = "not json at all"
        stderr = ""
        timed_out = False

    def fake_run_command(workspace, command, timeout=120):
        return _FakeResult()

    monkeypatch.setattr(semgrep_verify_module, "run_command", fake_run_command)

    result = await run_semgrep_verify(dotnet_sast_workspace, _finding(), settings={})

    assert result["passed"] is False
    assert result["raw"] == {}
    assert result["error"] is not None


@pytest.mark.asyncio
async def test_default_config_uses_registry_rule_id(monkeypatch, dotnet_sast_workspace):
    captured = {}

    class _FakeResult:
        stdout = '{"results": []}'
        stderr = ""
        timed_out = False

    def fake_run_command(workspace, command, timeout=120):
        captured["command"] = command
        return _FakeResult()

    monkeypatch.setattr(semgrep_verify_module, "run_command", fake_run_command)

    await run_semgrep_verify(dotnet_sast_workspace, _finding(), settings={})

    assert captured["command"] == [
        "semgrep",
        "--config",
        f"r/{RULE_ID}",
        "--json",
        "--quiet",
        "src/Controllers/ProductController.cs",
    ]


@pytest.mark.asyncio
async def test_settings_override_semgrep_config(monkeypatch, dotnet_sast_workspace):
    captured = {}

    class _FakeResult:
        stdout = '{"results": []}'
        stderr = ""
        timed_out = False

    def fake_run_command(workspace, command, timeout=120):
        captured["command"] = command
        return _FakeResult()

    monkeypatch.setattr(semgrep_verify_module, "run_command", fake_run_command)

    settings = {"sast": {"semgrep_config": "/local/rules/csharp.yml"}}
    await run_semgrep_verify(dotnet_sast_workspace, _finding(), settings=settings)

    assert "/local/rules/csharp.yml" in captured["command"]


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep is not installed in this environment")
async def test_real_semgrep_invocation_with_nonexistent_config_resolves_cleanly(dotnet_sast_workspace):
    # Only exercised when semgrep is genuinely on PATH. A deliberately
    # nonexistent registry rule id should make semgrep itself fail (network
    # or "not found"), which run_semgrep_verify must still report cleanly
    # rather than raise.
    finding = {"id": "definitely.not.a.real.semgrep.rule.id", "file": "src/Controllers/ProductController.cs"}
    result = await run_semgrep_verify(dotnet_sast_workspace, finding, settings={})
    assert isinstance(result, dict)
    assert "passed" in result and "raw" in result and "error" in result
