"""Bounded-concurrency, retrying, dedup'd driver for running a compiled
LangGraph graph over a stream of `Job`s -- the scale-critical path for
2000+ repos. Pragmatic and correct over clever.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from remediation_agent.execution.job import Job
from remediation_agent.execution.job_source import JobSource
from remediation_agent.execution.result_sink import ResultSink

logger = logging.getLogger(__name__)

_DEDUP_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class WorkerPool:
    """Fixed-size pool of coroutines pulling `Job`s from `job_source`,
    invoking `graph_factory()`'s compiled graph per job with a timeout and
    exponential-backoff retry on transient errors, and writing results via
    `result_sink`. Cross-process dedup is a sqlite `jobs` table keyed by
    `job_id` -- a job already marked `"done"` is skipped rather than
    reprocessed.

    `graph_factory` is a zero-arg callable returning a compiled graph. It is
    called once, lazily, inside `run()` -- not at construction time -- so
    the caller controls *when* the graph (and whatever checkpointer it was
    compiled against) comes into existence. The checkpointer's own
    lifecycle is intentionally the caller's responsibility, not the pool's:
    this constructor takes a `dedup_db_path` for the pool's own dedup
    bookkeeping but no `checkpoint_db_path`, since a checkpointer is an
    async-context-managed resource (a live sqlite connection that must stay
    open for the whole pool run) that naturally belongs to whoever opens
    it. Typical wiring (see `cli.py`'s `worker` subcommand):

        async with build_checkpointer(settings.checkpoint_db_path) as cp:
            pool = WorkerPool(
                graph_factory=lambda: build_graph(checkpointer=cp),
                job_source=job_source, result_sink=result_sink,
                concurrency=..., per_job_timeout=..., max_retries=...,
                dedup_db_path=settings.dedup_db_path,
            )
            await pool.run()
    """

    def __init__(
        self,
        graph_factory: Callable[[], Any],
        job_source: JobSource,
        result_sink: ResultSink,
        concurrency: int,
        per_job_timeout: int,
        max_retries: int,
        dedup_db_path: str,
    ) -> None:
        self.graph_factory = graph_factory
        self.job_source = job_source
        self.result_sink = result_sink
        self.concurrency = concurrency
        self.per_job_timeout = per_job_timeout
        self.max_retries = max_retries
        self.dedup_db_path = dedup_db_path

    async def run(self) -> None:
        Path(self.dedup_db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.dedup_db_path) as db:
            await db.execute(_DEDUP_SCHEMA)
            await db.commit()

            graph = self.graph_factory()

            # One coordinator task feeds a shared queue from job_source.stream();
            # `concurrency` workers pull from that queue. Simpler and safer than
            # having every worker call stream() independently -- FileJobSource's
            # stream() polls a directory and moves files as it consumes them, so
            # N independent pollers would race on the same files.
            queue: asyncio.Queue[Job] = asyncio.Queue()

            async def _feed() -> None:
                async for job in self.job_source.stream():
                    await queue.put(job)

            feeder = asyncio.create_task(_feed())
            workers = [
                asyncio.create_task(self._worker_loop(graph, db, queue))
                for _ in range(self.concurrency)
            ]
            try:
                await asyncio.gather(feeder, *workers)
            finally:
                feeder.cancel()
                for worker in workers:
                    worker.cancel()

    async def _worker_loop(
        self, graph: Any, db: aiosqlite.Connection, queue: "asyncio.Queue[Job]"
    ) -> None:
        while True:
            job = await queue.get()
            try:
                await self._process(graph, db, job)
            except Exception:
                logger.exception("unhandled error processing job %s", job.job_id)
            finally:
                queue.task_done()

    async def _process(self, graph: Any, db: aiosqlite.Connection, job: Job) -> None:
        cursor = await db.execute("SELECT status FROM jobs WHERE job_id = ?", (job.job_id,))
        row = await cursor.fetchone()
        if row is not None and row[0] == "done":
            logger.info("job %s already completed; skipping (dedup)", job.job_id)
            return

        await self._mark(db, job.job_id, "running")

        attempt = 0
        last_error: Exception | None = None
        while attempt <= self.max_retries:
            try:
                result = await asyncio.wait_for(
                    graph.ainvoke(job.payload, config={"configurable": {"thread_id": job.job_id}}),
                    timeout=self.per_job_timeout,
                )
            except Exception as exc:
                # A raised exception here is unexpected: every graph node is
                # written to catch its own errors and return a structured
                # decision, never to raise. So anything that does escape
                # (timeout, transient network/IO, an actual bug) is treated
                # as retryable rather than assumed to be a permanent
                # validation/logic failure -- a run that completes with
                # all-unsupported/failed units is a normal, non-exceptional
                # result and is never retried.
                last_error = exc
                attempt += 1
                if attempt > self.max_retries:
                    break
                backoff = 2**attempt
                logger.warning(
                    "job %s attempt %s failed (%r); retrying in %ss",
                    job.job_id, attempt, exc, backoff,
                )
                await asyncio.sleep(backoff)
                continue

            await self.result_sink.write(job, result.get("run_summary") or result)
            await self._mark(db, job.job_id, "done")
            return

        logger.error("job %s failed after %s attempts: %r", job.job_id, attempt, last_error)
        await self.result_sink.write(job, {"error": str(last_error), "job_id": job.job_id})
        await self._mark(db, job.job_id, "failed")

    async def _mark(self, db: aiosqlite.Connection, job_id: str, status: str) -> None:
        await db.execute(
            "INSERT INTO jobs (job_id, status, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET status = excluded.status, "
            "updated_at = excluded.updated_at",
            (job_id, status, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
