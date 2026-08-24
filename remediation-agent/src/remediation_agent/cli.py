"""Command-line entry point: `remediation-agent run-once <payload.json>` and
`remediation-agent worker --dir <jobs-dir> --concurrency N`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

# Loaded before anything reads os.environ (get_settings(), _build_providers()
# in llm/glc_gateway.py, etc.) -- `python-dotenv` was already a declared
# dependency but nothing actually called this; provider API keys in a local
# .env were silently inert until now. Only sets variables not already
# present in the real environment (load_dotenv's default), so an operator's
# actual exported secrets always win over a checked-in-adjacent .env file.
# Must run before the imports below: registering allowed commands and
# resolving settings both read os.environ at import/call time.
load_dotenv()

from remediation_agent.config import apply_command_allowlist, get_settings  # noqa: E402

# Importing these (before apply_command_allowlist() runs) is what makes
# adapters and SAST support register their commands into the allowlist
# union -- see config.py's apply_command_allowlist() docstring. `graph.build`
# (imported lazily inside _run_once/_worker, after apply_command_allowlist()
# already ran) is too late for this: registration has to happen before the
# allowlist snapshot is taken, not merely before any command actually runs.
import remediation_agent.ecosystems.registry  # noqa: E402,F401  (import for side effect)
import remediation_agent.sast  # noqa: E402,F401  (import for side effect: registers "semgrep")


def _run_once(args: argparse.Namespace) -> None:
    from remediation_agent.graph.build import build_graph

    with open(args.payload_path, encoding="utf-8") as fh:
        payload = json.load(fh)

    graph = build_graph(checkpointer=None)
    result = asyncio.run(graph.ainvoke(payload))

    output = result.get("run_summary")
    if output is None:
        output = {"ingest_error": result.get("ingest_error")}
    print(json.dumps(output, indent=2, default=str))


def _worker(args: argparse.Namespace) -> None:
    from remediation_agent.execution.checkpoint import build_checkpointer
    from remediation_agent.execution.job_source import FileJobSource
    from remediation_agent.execution.pool import WorkerPool
    from remediation_agent.execution.result_sink import FileResultSink
    from remediation_agent.graph.build import build_graph

    settings = get_settings()
    job_source = FileJobSource(args.dir)
    result_sink = FileResultSink(f"{args.dir}/results")

    async def _main() -> None:
        async with build_checkpointer(settings.checkpoint_db_path) as checkpointer:
            pool = WorkerPool(
                graph_factory=lambda: build_graph(checkpointer=checkpointer),
                job_source=job_source,
                result_sink=result_sink,
                concurrency=args.concurrency,
                per_job_timeout=settings.per_job_timeout_seconds,
                max_retries=settings.max_retries,
                dedup_db_path=settings.dedup_db_path,
            )
            await pool.run()

    asyncio.run(_main())


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    # httpx (and httpcore under it) log the full request URL at INFO level.
    # Gemini's REST API puts the API key directly in the URL as a `?key=...`
    # query parameter -- there is no header-based alternative -- so leaving
    # httpx at INFO prints a live secret into stderr on every Gemini call via
    # llm/glc_gateway.py. This is not hypothetical: it happened during this
    # project's own testing. WARNING still surfaces real httpx errors.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(prog="remediation-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_once = subparsers.add_parser(
        "run-once", help="Run the remediation graph once against a single payload file."
    )
    run_once.add_argument("payload_path", help="Path to an orchestrator payload JSON file.")
    run_once.set_defaults(func=_run_once)

    worker = subparsers.add_parser(
        "worker", help="Run a bounded-concurrency worker pool against a directory of jobs."
    )
    worker.add_argument("--dir", required=True, help="Directory watched for *.json payload files.")
    worker.add_argument(
        "--concurrency", type=int, default=get_settings().worker_concurrency, help="Max concurrent jobs."
    )
    worker.set_defaults(func=_worker)

    args = parser.parse_args()
    # Called once here, after remediation_agent.ecosystems.registry was
    # imported above, so every registered adapter's allowed_commands() is
    # already unioned into S17_ALLOWED_COMMANDS before any node runs.
    apply_command_allowlist()
    args.func(args)


if __name__ == "__main__":
    main()
