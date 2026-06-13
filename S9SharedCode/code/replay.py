"""Replay a persisted Session 8 run, one node at a time.

Stdin-driven. Reads `state/sessions/<sid>/` and walks its NodeState
records in completion order. For each node prints a fixed block, then
waits for the user to advance.

Usage:
    uv run python replay.py <session_id>

Keys:
    enter   advance to next node
    p       expand the full rendered prompt that was sent to the gateway
    o       expand the full AgentResult.output JSON
    b       browser report (8-item: goal / DAG / path / actions /
            screenshots / extracted data / comparison table / cost)
    q       quit
"""

from __future__ import annotations

import json
import sys

from persistence import SessionStore, list_sessions
from schemas import NodeState


def _print_block(i: int, n: int, st: NodeState) -> None:
    r = st.result
    skill = st.skill
    elapsed = f"{r.elapsed_s:.1f}s" if r and r.elapsed_s else "—"
    provider = (r.provider if r and r.provider else "—")
    retries = st.retries
    tools = ""
    print()
    print(f"node {i} / {n}")
    print(f"  agent      {skill}")
    print(f"  status     {st.status}")
    print(f"  elapsed    {elapsed}")
    print(f"  provider   {provider}")
    print(f"  retries    {retries}")
    print(f"  inputs     {', '.join(st.inputs) or '(none)'}")
    if tools:
        print(f"  tools      {tools}")
    if r and r.error:
        print(f"  error      {r.error[:240]}")
    if r and r.output:
        try:
            out_preview = json.dumps(r.output, ensure_ascii=False)
        except (TypeError, ValueError):
            out_preview = str(r.output)
        if len(out_preview) > 500:
            out_preview = out_preview[:500] + "…"
        print(f"  output     {out_preview}")


def _expand_prompt(st: NodeState) -> None:
    print()
    print("─" * 78)
    print(st.prompt_sent or "(no prompt captured)")
    print("─" * 78)


def _expand_output(st: NodeState) -> None:
    print()
    print("─" * 78)
    if st.result and st.result.output:
        print(json.dumps(st.result.output, indent=2, ensure_ascii=False))
    else:
        print("(no output)")
    print("─" * 78)


def _expand_browser(st: NodeState, query: str, states: list[NodeState]) -> None:
    """Print the 8-item browser report for a browser node."""
    if st.skill != "browser":
        print("  (not a browser node — press 'b' only on browser nodes)")
        return
    r = st.result
    out = (r.output if r else None) or {}
    replay = out.get("replay") or {}
    W = 78

    print()
    print("═" * W)
    print(f"BROWSER REPORT  {st.node_id}")
    print("═" * W)

    # 1. Original user goal
    print("\n① GOAL")
    print(f"  {query[:300]}")

    # 2. Planner DAG
    dag = replay.get("planner_dag") or []
    print("\n② PLANNER DAG")
    print(f"  {' → '.join(dag) if dag else '(not recorded)'}")

    # 3. Browser path chosen
    path = out.get("path", "?")
    print("\n③ PATH CHOSEN")
    print(f"  {path}")

    # 4. Browser actions taken
    actions = out.get("actions") or []
    turns = out.get("turns", 0)
    print(f"\n④ BROWSER ACTIONS  ({turns} turn(s))")
    if actions:
        for a in actions[:20]:
            t = a.get("turn", "?")
            acts = a.get("actions") or a.get("action", "?")
            outcome = (a.get("outcome") or "")[:60]
            print(f"  turn {t}: {str(acts)[:80]}  → {outcome}")
        if len(actions) > 20:
            print(f"  … {len(actions) - 20} more action(s) omitted")
    else:
        print("  (none recorded)")

    # 5. Screenshots
    screenshots = replay.get("screenshots") or []
    print(f"\n⑤ SCREENSHOTS  ({len(screenshots)} file(s))")
    if screenshots:
        for s in screenshots[:10]:
            print(f"  {s}")
        if len(screenshots) > 10:
            print(f"  … {len(screenshots) - 10} more")
    else:
        print("  (none recorded)")

    # 6. Extracted data
    content = out.get("content") or ""
    print("\n⑥ EXTRACTED DATA")
    if content:
        preview = content[:500]
        print(f"  {preview}{'…' if len(content) > 500 else ''}")
    else:
        print("  (none)")

    # 7. Final comparison table — look for formatter node's final_answer
    print("\n⑦ COMPARISON TABLE")
    formatter_answer = None
    for ns in states:
        if ns.skill == "formatter" and ns.result and ns.result.output:
            fa = ns.result.output.get("final_answer") or ""
            if fa:
                formatter_answer = fa
                break
    ct = out.get("comparison_table") or []
    if formatter_answer:
        print(f"  {formatter_answer[:800]}{'…' if len(formatter_answer) > 800 else ''}")
    elif ct:
        print(json.dumps(ct, indent=2, ensure_ascii=False)[:600])
    else:
        print("  (see formatter node — press 'o' on that node)")

    # 8. Turn count and cost summary
    cs = out.get("cost_summary") or {}
    print("\n⑧ COST SUMMARY")
    if cs:
        print("  " + "  |  ".join(f"{k}: {v}" for k, v in cs.items()))
    else:
        elapsed = (r.elapsed_s if r else 0) or 0
        print(f"  path: {path}  |  turns: {turns}  |  elapsed: {elapsed:.1f}s")

    print("\n" + "═" * W)


def replay(session_id: str) -> int:
    store = SessionStore(session_id)
    states = store.read_all_nodes()
    if not states:
        print(f"replay: no nodes under state/sessions/{session_id}/", file=sys.stderr)
        return 2

    query = store.read_query() or ""
    print(f"session  {session_id}")
    print(f"query    {query[:200]}")
    print(f"nodes    {len(states)}")
    print()
    print("press enter to advance, p to expand prompt, o to expand output, "
          "b for browser report, q to quit")

    i = 0
    while i < len(states):
        st = states[i]
        _print_block(i + 1, len(states), st)
        try:
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if cmd == "q":
            return 0
        if cmd == "p":
            _expand_prompt(st)
            continue
        if cmd == "o":
            _expand_output(st)
            continue
        if cmd == "b":
            _expand_browser(st, query, states)
            continue
        i += 1
    print("\n(end of session)")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        sessions = list_sessions()
        if not sessions:
            print("replay: no sessions under state/sessions/", file=sys.stderr)
            return 2
        print("available sessions:")
        for s in sessions:
            print(f"  {s}")
        print("\nusage: uv run python replay.py <session_id>")
        return 0
    return replay(args[0])


if __name__ == "__main__":
    sys.exit(main())
