"""Environment-driven settings, and the one place that widens session-17's
command allowlist.

``s17code.coding.exec.run_command`` refuses any program not in
``S17_ALLOWED_COMMANDS``. We need ``dotnet``/``mvn``/``gradle``/``gradlew``/``java``
on top of session-17's own defaults (pytest, python, uv, ruff, mypy, git, node,
npm) so build/test gates for .NET and Java repos can run at all. This is done
purely by setting the env var session-17 already reads for that purpose --
never by editing session-17's source.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# session-17's own defaults (s17code/coding/exec.py DEFAULT_ALLOWLIST), repeated
# here only so the union is visible in one place -- not imported, since
# s17code.coding.exec computes its allowlist lazily from the env var at call
# time and has no importable constant we could union against directly.
S17_DEFAULT_ALLOWLIST = ("pytest", "python", "python3", "uv", "ruff", "mypy", "git", "node", "npm")

# Extended per registered ecosystem adapter at import time via
# `register_allowed_commands`; kept as a module-level set so every adapter's
# `allowed_commands()` can contribute without the graph needing to know them.
_extra_allowed_commands: set[str] = set()


def register_allowed_commands(commands: tuple[str, ...]) -> None:
    """Called by ecosystems/registry.py when an adapter registers itself."""
    _extra_allowed_commands.update(commands)


def apply_command_allowlist() -> None:
    """Union session-17's defaults with every registered adapter's commands,
    and set S17_ALLOWED_COMMANDS so s17code.coding.exec.run_command honors it.

    Idempotent and safe to call repeatedly (e.g. once per worker process
    start, and again after new adapters register).
    """
    union = sorted(set(S17_DEFAULT_ALLOWLIST) | _extra_allowed_commands)
    os.environ["S17_ALLOWED_COMMANDS"] = ",".join(union)


@dataclass(frozen=True)
class Settings:
    """Process-wide configuration, all overridable via env vars."""

    # Concurrency / scale
    worker_concurrency: int = field(default_factory=lambda: int(os.getenv("REMEDIATION_CONCURRENCY", "10")))
    per_job_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("REMEDIATION_JOB_TIMEOUT", "1800"))
    )
    max_retries: int = field(default_factory=lambda: int(os.getenv("REMEDIATION_MAX_RETRIES", "2")))

    # Checkpointing / dedup
    checkpoint_db_path: str = field(
        default_factory=lambda: os.getenv("REMEDIATION_CHECKPOINT_DB", ".remediation/checkpoints.sqlite")
    )
    dedup_db_path: str = field(
        default_factory=lambda: os.getenv("REMEDIATION_DEDUP_DB", ".remediation/jobs.sqlite")
    )

    # LLM (only consulted by the SAST LLM-fallback tier, the SCA-ambiguous
    # fallback, and the optional adversarial validator -- the default SCA
    # path makes no LLM call). "glc" reuses session-17's own multi-provider
    # fallback chain (glc_v5's glc.providers, LLM_ORDER, ollama first) --
    # see llm/glc_gateway.py. `llm_model` is only read by the "anthropic"
    # branch; "glc"'s per-provider models come from each provider's own
    # *_MODEL env var (GROQ_MODEL, OLLAMA_MODEL, etc.), already set wherever
    # session-17's own gateway is configured.
    llm_provider: str = field(default_factory=lambda: os.getenv("REMEDIATION_LLM_PROVIDER", "glc"))
    llm_model: str = field(default_factory=lambda: os.getenv("REMEDIATION_LLM_MODEL", "claude-sonnet-5"))
    enable_sca_llm_fallback: bool = field(
        default_factory=lambda: os.getenv("REMEDIATION_SCA_LLM_FALLBACK", "false").lower() == "true"
    )
    enable_adversarial_validation: bool = field(
        default_factory=lambda: os.getenv("REMEDIATION_ADVERSARIAL_VALIDATION", "false").lower() == "true"
    )
    # Total attempts (first try + retries) allowed for an LLM-authored SAST
    # fix that a downstream gate rejects (scope, build, test, semgrep
    # re-verification, or adversarial validation). A deterministic template
    # fix is never retried -- see graph/nodes/unit/_retry.py.
    sast_max_attempts: int = field(
        default_factory=lambda: int(os.getenv("REMEDIATION_SAST_MAX_ATTEMPTS", "3"))
    )

    # Exec sandboxing (passed straight through to s17code.coding.exec via env,
    # documented here so both live in one place)
    exec_container: bool = field(default_factory=lambda: os.getenv("S17_EXEC_CONTAINER", "") == "1")

    # Git identity used for local commits created by the `decide` node
    git_author_name: str = field(default_factory=lambda: os.getenv("REMEDIATION_GIT_AUTHOR", "remediation-agent"))
    git_author_email: str = field(
        default_factory=lambda: os.getenv("REMEDIATION_GIT_EMAIL", "remediation-agent@localhost")
    )


def get_settings() -> Settings:
    return Settings()
