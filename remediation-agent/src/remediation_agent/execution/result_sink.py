"""Where a job's remediation output lands -- a small Protocol so a real
result store can be swapped in later without touching the graph or pool.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from remediation_agent.execution.job import Job


@runtime_checkable
class ResultSink(Protocol):
    async def write(self, job: Job, result: dict) -> None: ...


class FileResultSink:
    def __init__(self, output_dir: str) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def write(self, job: Job, result: dict) -> None:
        path = self.output_dir / f"{job.job_id.replace(':', '_')}.json"
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
