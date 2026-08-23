"""LangGraph checkpointer factory.

Sqlite for local/dev and single-process pools (sqlite's single-writer lock
is fine within one pool, not across many worker processes -- swap to a
Postgres-backed checkpointer, e.g. `langgraph-checkpoint-postgres`, for true
multi-process/multi-machine scale; same call site in `execution/pool.py`,
different `build_checkpointer` implementation).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path


@asynccontextmanager
async def build_checkpointer(db_path: str):
    """Async context manager yielding an `AsyncSqliteSaver` opened at `db_path`.

    Usage: `async with build_checkpointer(path) as checkpointer: ...`
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        yield saver
