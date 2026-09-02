"""Vendored execution sandbox: `exec.py`, copied from session-17's
`s17code.coding.exec`.

`Workspace` is deliberately NOT vendored here -- remediation-agent already
depends on `s17code.coding.workspace.Workspace` everywhere else (`ingest.py`,
`ecosystems/*`, `sast/*`, ...), and `exec.py`'s `run_command` only ever reads
`workspace.root` off it, so it imports that same shared `Workspace` rather
than defining a second, unused class of its own. `edit.py`/`search.py`/
`guard.py` also stay in `s17code.coding` (manifest locating/patching, not
execution). This subset exists so build/test-gate execution
(`validate_build_test.py`, `decide.py`, `semgrep_verify.py`, and the
LLM-fix/adversarial-validator tool loops) does not depend on the rest of the
90-file `eagv3-s17code` package (its agent runtime, workers, UI, telemetry --
none of which remediation-agent uses) just to run a command.
"""
