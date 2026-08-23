"""Where `Job`s come from -- a small Protocol so a real broker (SQS/Kafka/
Temporal) can be swapped in later without touching the graph or worker pool.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from remediation_agent.execution.job import Job

logger = logging.getLogger(__name__)


@runtime_checkable
class JobSource(Protocol):
    async def stream(self) -> AsyncIterator[Job]: ...


class InProcessJobSource:
    """Backed by an `asyncio.Queue`, for tests and in-process callers."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Job] = asyncio.Queue()

    async def submit(self, payload: dict) -> None:
        await self._queue.put(Job.from_payload(payload))

    async def stream(self) -> AsyncIterator[Job]:
        while True:
            yield await self._queue.get()


class FileJobSource:
    """Watches `watch_dir` for `*.json` payload files.

    Plain polling (`os.listdir` + a seen-set) rather than an external
    file-watching library -- simple, dependency-free, and more than fast
    enough at `poll_interval` cadence for a batch/CI-triggered workload.
    Each picked-up file is parsed as a payload, yielded as a `Job`, then
    moved into `processed/` so it is never re-read on the next poll.
    """

    def __init__(self, watch_dir: str, poll_interval: float = 2.0) -> None:
        self.watch_dir = Path(watch_dir)
        self.poll_interval = poll_interval
        self.processed_dir = self.watch_dir / "processed"
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    async def stream(self) -> AsyncIterator[Job]:
        while True:
            for name in sorted(os.listdir(self.watch_dir)):
                if not name.endswith(".json"):
                    continue
                path = self.watch_dir / name
                if not path.is_file():
                    continue
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    job = Job.from_payload(payload)
                except Exception:
                    logger.exception("failed to parse job payload %s; skipping", path)
                    # Move it aside anyway so a malformed file doesn't get
                    # re-attempted forever on every poll.
                    shutil.move(str(path), str(self.processed_dir / name))
                    continue

                shutil.move(str(path), str(self.processed_dir / name))
                yield job

            await asyncio.sleep(self.poll_interval)
