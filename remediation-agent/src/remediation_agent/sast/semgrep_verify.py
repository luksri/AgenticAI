"""Re-run Semgrep against a patched file and confirm the flagged rule no
longer fires.

This is the strongest available validation for a SAST fix: build/test gates
can't tell that a deserialization call became safe, but re-running the exact
Semgrep rule that flagged it can. `validate_build_test.py` (extended
separately) is expected to run this unconditionally for every SAST unit,
regardless of fix tier (template or LLM).

v1 limitation (documented, not a bug): the default `--config` points at the
public Semgrep registry (`r/<rule-id>`), which assumes network access to
`semgrep.dev`. A real deployment should instead point `semgrep_config` at
whatever local ruleset the orchestrator's own Semgrep run used (a path to a
local rules file/dir), via `settings["sast"]["semgrep_config"]`, so
re-verification uses the exact same rule definition that produced the
finding rather than trusting the registry to still have a byte-identical
rule under the same id.
"""
from __future__ import annotations

import json
from typing import Any

from s17code.coding.exec import CommandError, run_command
from s17code.coding.workspace import Workspace

DEFAULT_TIMEOUT_SECONDS = 120


async def run_semgrep_verify(workspace: Workspace, finding: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Run `semgrep --config <config> --json --quiet <file>` and check whether
    `finding["id"]`'s rule still fires.

    Returns ``{"passed": bool, "raw": dict, "error": str | None}``. Never
    raises: a missing `semgrep` binary (`CommandError`), a non-zero exit that
    still produced no parseable JSON, or malformed JSON output are all
    reported as `{"passed": False, "raw": {}, "error": <message>}` so the
    calling validation node can decide how to treat "couldn't verify" --
    that policy decision belongs to `validate_build_test.py`, not here.
    """
    rule_id = finding.get("id")
    file_path = finding.get("file")
    if not rule_id or not file_path:
        return {
            "passed": False,
            "raw": {},
            "error": "finding has no 'id' and/or 'file' to re-verify against",
        }

    sast_settings = (settings or {}).get("sast") or {}
    config = sast_settings.get("semgrep_config") or f"r/{rule_id}"

    # `--config`, `--json`, `--quiet` and a config string like
    # `r/csharp.lang.security.insecure-deserialization.insecure-deserialization`
    # contain only letters, digits, dots, slashes and hyphens -- none of which
    # appear in s17code.coding.exec.SHELL_METACHARACTERS
    # (`; && || | ` $( > < \n`), so this is safe to pass as a single argv
    # token through the no-shell `run_command`.
    command = ["semgrep", "--config", config, "--json", "--quiet", file_path]

    try:
        result = run_command(workspace, command, timeout=DEFAULT_TIMEOUT_SECONDS)
    except CommandError as exc:
        return {"passed": False, "raw": {}, "error": f"semgrep could not be run: {exc}"}

    if result.timed_out:
        return {
            "passed": False,
            "raw": {},
            "error": f"semgrep timed out after {DEFAULT_TIMEOUT_SECONDS}s",
        }

    try:
        raw = json.loads(result.stdout) if result.stdout else {}
    except json.JSONDecodeError as exc:
        return {
            "passed": False,
            "raw": {},
            "error": f"semgrep produced unparseable JSON output: {exc}; stderr={result.stderr[:500]!r}",
        }

    if not isinstance(raw, dict):
        return {
            "passed": False,
            "raw": {},
            "error": f"semgrep JSON output was not an object: {type(raw).__name__}",
        }

    findings_results = raw.get("results")
    if findings_results is None:
        return {
            "passed": False,
            "raw": raw,
            "error": "semgrep JSON output has no 'results' key",
        }

    if findings_results:
        # A match is itself positive proof a real scan happened -- the rule
        # id resolved to something and it found the pattern. No need to
        # check paths.scanned when we already have stronger evidence.
        return {"passed": False, "raw": raw, "error": None}

    # An empty `results` list alone is ambiguous: it means either "genuinely
    # fixed" or "the config didn't resolve to any rule" (verified against
    # this project's actual sample rule id: `--config r/<that id>` loaded
    # ZERO rules and exited 0 with empty results, indistinguishable from a
    # real pass by `results` alone -- finding["id"]'s format has no guarantee
    # of matching the public registry's paths). `paths.scanned` is what
    # actually distinguishes them: non-empty only when semgrep ran a real
    # rule against a real file.
    scanned = (raw.get("paths") or {}).get("scanned") or []
    if not scanned:
        return {
            "passed": False,
            "raw": raw,
            "error": (
                f"semgrep scanned zero files for config {config!r}: the config "
                "most likely did not resolve to any rule, so an empty 'results' "
                "list here does not mean the finding was fixed. Point "
                "settings.sast.semgrep_config at a local ruleset that genuinely "
                "contains this rule id rather than relying on the public registry."
            ),
        }

    return {"passed": True, "raw": raw, "error": None}
