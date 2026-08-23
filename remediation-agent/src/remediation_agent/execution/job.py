"""A unit of work handed to the worker pool: one orchestrator payload."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Job:
    job_id: str
    payload: dict
    attempt: int = 0

    @classmethod
    def from_payload(cls, payload: dict) -> "Job":
        # Doubles as the LangGraph checkpointer thread_id: a resubmission of
        # the same commit resumes at the last completed node instead of
        # reprocessing from scratch.
        run_context = payload["run_context"]
        job_id = f"{run_context['project_id']}:{run_context['commit_sha']}"
        return cls(job_id=job_id, payload=payload)
