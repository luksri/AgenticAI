"""The orchestrator -> remediation-agent data contract.

This mirrors the orchestrator's JSON payload exactly. The orchestrator is a
separate, already-built, deterministic layer we do not touch or reimplement --
these models exist only to validate and normalize what it hands us.

Every model allows extra fields (`model_config = ConfigDict(extra="allow")`)
because the real payload's `settings` and `run_context` carry additional
CI-metadata / `.agent-config.yml` fields beyond the ones shown in the sample
payload we were given. Rejecting unknown fields would make this brittle
against the orchestrator's own evolution, which we have no control over.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LenientModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RunContext(LenientModel):
    correlation_id: str
    pipeline_id: str | None = None
    project_id: str
    commit_sha: str


class Source(LenientModel):
    mode: str = "workspace"
    path: str
    scope: str = "full"


class Scope(LenientModel):
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class Gates(LenientModel):
    build: str = ""
    test: str = ""


class Settings(LenientModel):
    severity: list[str] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    gates: Gates = Field(default_factory=Gates)


class Enrichment(LenientModel):
    nvd: dict[str, Any] = Field(default_factory=dict)
    epss: float | None = None
    kev: bool | None = None


class Risk(LenientModel):
    score: float | None = None
    tier: str | None = None


class Finding(LenientModel):
    id: str
    severity: str
    # Deliberately `str`, not a strict enum: unrecognized categories (future
    # secrets/IaC findings) must flow through validation and be handled by
    # strategies/registry.py's "unsupported" fallback, not rejected here.
    category: str
    file: str

    # SCA (Trivy) shape: a package and the version that closes the finding.
    component: str | None = None
    fixed_version: str | None = None

    # SAST (Semgrep) shape: `id` above is the rule id, not a CVE, when
    # `tool == "semgrep"`. `line`/`snippet` locate the vulnerable code instead
    # of a manifest entry; `cwe_ids` is the key used for curated per-vulnerability-
    # class guidance (see sast/guidance.py) since individual rule ids are too
    # numerous to curate against directly.
    tool: str | None = None
    lane: str | None = None
    title: str | None = None
    line: int | None = None
    snippet: str | None = None
    cwe_ids: list[str] = Field(default_factory=list)
    # Orchestrator-internal correlation metadata (cross-referenced against
    # other findings). Not well-enough specified to gate remediation behavior
    # on; carried through as opaque passthrough only.
    correlated: bool | None = None

    enrichment: Enrichment = Field(default_factory=Enrichment)
    risk: Risk = Field(default_factory=Risk)


class OrchestratorPayload(LenientModel):
    run_context: RunContext
    source: Source
    settings: Settings = Field(default_factory=Settings)
    findings: list[Finding] = Field(default_factory=list)
