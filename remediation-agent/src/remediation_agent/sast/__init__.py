"""SAST (Semgrep) remediation support.

Importing this package registers "semgrep" into the shared command allowlist,
the same extension mechanism `ecosystems/registry.py` uses for
`dotnet`/`mvn`/`gradle` -- pure env-var configuration via
`config.register_allowed_commands`, never a session-17 source edit.
"""
from remediation_agent.config import register_allowed_commands

register_allowed_commands(("semgrep",))
