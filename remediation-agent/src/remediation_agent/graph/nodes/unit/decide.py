"""Per-unit subgraph, terminal node: commit a passing fix, or pass through a
decision an earlier node already made.

If `state["decision"]` is already set, an earlier node in the chain decided
this unit is done (e.g. `unsupported_ecosystem`, `fix_failed_validation`) and
routing sent control straight here. Any workspace cleanup for a failing
decision (`workspace.reset()`) already happened in whichever node set that
decision -- this function does not re-reset, it just returns unchanged.

If no `decision` is set yet, every prior gate passed: branch, stage, and
commit the fix locally. This project never pushes or opens a PR (confirmed
out of scope), so the local commit itself is the reported output.

One exception: if `fix_result["already_satisfied"]` is set (the ecosystem
adapter found the component already at `fixed_version` -- e.g. a rerun of
the same finding against a repo an earlier run already fixed), there is
nothing to commit. That's reported as `pass` directly, without creating a
branch first and then discovering it has nothing to put on it.
"""
from __future__ import annotations

from typing import Any

from s17code.coding.exec import CommandError, run_command
from s17code.coding.workspace import Workspace, WorkspaceError

from remediation_agent.config import get_settings
from remediation_agent.graph.nodes.unit._git_identity import ensure_git_identity


async def decide(state: dict) -> dict[str, Any]:
    if state.get("decision"):
        return {}

    unit = state["unit"]
    fix_result = state.get("fix_result") or {}

    if fix_result.get("already_satisfied"):
        # The component (or SAST location) was already at the target state
        # before this run touched anything -- e.g. a rerun of the same
        # finding against a repo an earlier run already fixed. Genuinely
        # nothing to commit, not a failure: report `pass` without creating a
        # branch at all, rather than checking one out and then discovering
        # there's nothing to put on it.
        return {"decision": "pass", "branch": None, "commit_sha": None}

    workspace = Workspace.open(state["workspace_root"])
    settings = get_settings()
    branch_name = f"remediation/{unit['unit_id']}"

    try:
        ensure_git_identity(workspace, settings.git_author_name, settings.git_author_email)
        workspace.branch(branch_name)

        changed_files = state["fix_result"].get("changed_files", [])
        if not changed_files:
            raise CommandError("fix_result reported no changed_files to commit")
        run_command(workspace, ["git", "add", *changed_files])

        finding_ids = [f.get("id") for f in unit["findings"] if f.get("id")]
        old_version = state["fix_result"].get("old_version")
        new_version = state["fix_result"].get("new_version")
        component = unit.get("component") or unit.get("file")
        closes = f" (closes {', '.join(finding_ids)})" if finding_ids else ""
        if old_version and new_version:
            # No "->": run_command refuses any argv token containing a shell
            # metacharacter, including '>', even inside a -m message string.
            message = f"remediate: bump {component} from {old_version} to {new_version}{closes}"
        elif unit["category"] == "SAST":
            # SCA-shaped message doesn't fit: there's no version pair, just a
            # code fix. Use the findings' own titles when present (Semgrep
            # supplies one), falling back to the file so the message is never
            # empty.
            titles = sorted({f["title"] for f in unit["findings"] if f.get("title")})
            summary = "; ".join(titles) if titles else f"security finding in {unit['file']}"
            message = f"remediate: fix {summary}{closes}"
        else:
            message = f"remediate: fix {component}{closes}"

        run_command(workspace, ["git", "commit", "-m", message])
        sha_result = run_command(workspace, ["git", "rev-parse", "HEAD"])
        commit_sha = sha_result.stdout.strip()
    except (CommandError, WorkspaceError) as exc:
        # workspace.reset() alone is not enough here: it runs `git checkout --
        # .`, which restores the working tree from the INDEX, not HEAD. If
        # `git add` already staged the fix before `git commit` failed, that
        # leaves the bad state staged (and therefore still on disk) after
        # reset(). Explicitly unstage-and-restore from HEAD first.
        try:
            run_command(workspace, ["git", "restore", "--staged", "--worktree", "."])
        except CommandError:
            pass
        workspace.reset()
        return {"decision": "fix_failed", "error": str(exc)}

    return {"decision": "pass", "branch": branch_name, "commit_sha": commit_sha}
