"""Parent-graph entry node: validate the raw orchestrator payload.

`state` here is the raw dict LangGraph was invoked with -- the caller does
`graph.ainvoke({"run_context": ..., "source": ..., "settings": ..., "findings": ...})`,
i.e. the parsed JSON payload's top-level fields spread directly into initial
state. This node's whole job is to turn that untrusted dict into validated,
checkpointer-serializable state (plain str/dict/list -- never a live
`Workspace`, which every downstream node reopens itself from
`workspace_root`).
"""
from __future__ import annotations

from typing import Any

from s17code.coding.workspace import Workspace, WorkspaceError

from remediation_agent.schemas.payload import OrchestratorPayload


async def ingest(state: dict) -> dict[str, Any]:
    try:
        payload = OrchestratorPayload.model_validate(state)
    except Exception as exc:  # pydantic.ValidationError and friends
        return {"ingest_error": str(exc)}

    try:
        Workspace.open(payload.source.path)
    except WorkspaceError as exc:
        return {"ingest_error": str(exc)}

    return {
        "run_context": payload.run_context.model_dump(),
        "source": payload.source.model_dump(),
        "settings": payload.settings.model_dump(),
        "workspace_root": payload.source.path,
        "findings": [f.model_dump() for f in payload.findings],
        "ingest_error": None,
    }
