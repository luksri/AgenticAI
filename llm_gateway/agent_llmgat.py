"""
LLM agent that drives an MCP server.

Flow:
  1. Spawn ./mcp_server.py over stdio and list its tools.
  2. Convert the MCP tool schemas into a system-prompt block.
  3. Ask the LLM (via local llm_gateway) to plan one step at a time,
     replying ONLY with strict JSON: either a tool call or a final answer.
  4. Parse the JSON, call the tool through MCP, feed the result back,
     loop until the model returns {"final": ...}.

Why this shape:
  - Tool *definitions* come from the MCP server (single source of truth).
    The agent never hardcodes tool names or schemas.
  - llm_gateway does NOT translate native function-calling APIs across
    its 7 providers, so we use prompted JSON (works on every provider).
    We pin temperature=0 and strip ```json fences for robust parsing.
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# llm_gateway client lives one level up
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "llm_gateway"))
from client import LLM  # noqa: E402


# ---------- prompt construction ----------

SYSTEM_TEMPLATE = """You are a tool-calling agent. You CANNOT do arithmetic yourself —
you MUST call the provided tools for every add and every subtract, even trivial ones.

Output protocol (STRICT):
- Every reply is exactly ONE JSON object and NOTHING ELSE.
- No prose, no explanations, no markdown, no code fences.
- To call a tool:   {{"tool": "<name>", "args": {{...}}}}
- Final answer:     {{"final": <number>}}
- One step per reply. Wait for the tool_result before the next step.
- Read prior tool_result lines in the conversation; reuse those numbers
  instead of recomputing.

Available tools (from MCP server):
{tools_block}

Examples of valid replies (and ONLY these shapes are valid):
{{"tool": "add", "args": {{"a": 1, "b": 2}}}}
{{"tool": "subtract", "args": {{"a": 5, "b": 3}}}}
{{"final": 4}}
"""


def render_tools_block(tools) -> str:
    """Turn MCP tool listings into a compact human-readable block.

    We deliberately render parameters as `name: type` rather than dumping
    JSON Schema — when the prompt contains nested {"type":"object",...}
    fragments, smaller models tend to imitate that shape and emit broken
    "function call" JSON instead of our protocol.
    """
    lines = []
    for t in tools:
        props = (t.inputSchema or {}).get("properties", {}) or {}
        params = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in props.items())
        lines.append(f"- {t.name}({params}) — {t.description}")
    return "\n".join(lines)


# ---------- robust JSON extraction ----------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_llm_json(text: str) -> dict:
    """Extract the first JSON object from an LLM reply.

    Handles three common shapes:
      1. Pure JSON                     -> json.loads directly
      2. Fenced ```json ... ```        -> strip fences first
      3. JSON embedded in prose        -> grab the first {...} block
    """
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    # we require an object — bare scalars like "20" mean the model skipped
    # the protocol, so don't accept them
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    raise ValueError(f"Could not parse JSON object from LLM output:\n{text}")


def normalize_action(obj: dict) -> dict:
    """Map common tool-call dialects onto our canonical {tool, args} / {final} shape.

    Models RLHF'd for native function-calling sometimes emit alternative schemas
    even when prompted otherwise. Accepting a few known shapes keeps the agent
    robust without weakening the protocol.
    """
    if "final" in obj or ("tool" in obj and "args" in obj):
        return obj
    # Anthropic / OpenAI dialect: {"name": ..., "arguments": {...}}
    if "name" in obj and ("arguments" in obj or "parameters" in obj):
        return {"tool": obj["name"], "args": obj.get("arguments") or obj.get("parameters") or {}}
    # Parallel: {"tool_calls": [{"name":..., "arguments":...}, ...]}
    # We only honor the first call — our protocol is one-step-at-a-time.
    calls = obj.get("tool_calls") or obj.get("calls")
    if calls:
        first = calls[0]
        return {
            "tool": first.get("name") or first.get("tool"),
            "args": first.get("arguments") or first.get("args") or first.get("parameters") or {},
        }
    return obj  # let the caller raise "unknown tool"


# ---------- agent loop ----------

def _hr(title: str = "", ch: str = "─", width: int = 78) -> None:
    if title:
        print(f"\n{ch*3} {title} {ch*max(0, width - len(title) - 5)}")
    else:
        print(ch * width)


def _dump_messages(messages: list[dict], label: str) -> None:
    print(f"\n[{label}] full message history sent to LLM ({len(messages)} turns):")
    for i, m in enumerate(messages):
        role = m["role"].upper().ljust(9)
        content = m["content"]
        if len(content) > 220:
            content = content[:220] + f"... <+{len(content)-220} chars>"
        print(f"  #{i:02d} {role} {content}")


async def run_agent(numbers: list[float], max_steps: int = 8) -> float:
    a, b, c, d = numbers
    user_task = (
        f"Inputs: a={a}, b={b}, c={c}, d={d}.\n"
        f"Compute (a+b) + (c-d) by calling the tools. "
        f"Reply with one JSON object now."
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_server.py"))],
    )

    _hr("BOOT")
    print(f"[boot] python    : {sys.executable}")
    print(f"[boot] mcp script: {server_params.args[0]}")
    print(f"[boot] task numbers: a={a}  b={b}  c={c}  d={d}")
    print(f"[boot] expected:   ({a}+{b}) + ({c}-{d}) = {(a+b)+(c-d)}")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            _hr("MCP HANDSHAKE")
            init_result = await session.initialize()
            print(f"[mcp] server name    : {init_result.serverInfo.name}")
            print(f"[mcp] server version : {init_result.serverInfo.version}")
            print(f"[mcp] protocol       : {init_result.protocolVersion}")

            # 1. Discover tools from the MCP server
            _hr("MCP TOOL DISCOVERY")
            tool_list = (await session.list_tools()).tools
            print(f"[mcp] tools found: {len(tool_list)}")
            for t in tool_list:
                print(f"  - name        : {t.name}")
                print(f"    description : {t.description}")
                print(f"    inputSchema : {json.dumps(t.inputSchema)}")

            system_prompt = SYSTEM_TEMPLATE.format(
                tools_block=render_tools_block(tool_list)
            )
            tool_names = {t.name for t in tool_list}

            _hr("SYSTEM PROMPT (built from MCP tool list)")
            print(system_prompt)

            _hr("USER TASK")
            print(user_task)

            # 2. Drive the LLM in a step-by-step loop
            llm = LLM()
            # In-context few-shot: a tiny worked example trains the model to
            # imitate the JSON-only protocol. Far more reliable than rules alone.
            messages = [
                {"role": "user", "content": "Inputs: a=1, b=2, c=8, d=3. Compute (a+b)+(c-d)."},
                {"role": "assistant", "content": '{"tool": "add", "args": {"a": 1, "b": 2}}'},
                {"role": "user", "content": 'tool_result {"tool":"add","result":3}'},
                {"role": "assistant", "content": '{"tool": "subtract", "args": {"a": 8, "b": 3}}'},
                {"role": "user", "content": 'tool_result {"tool":"subtract","result":5}'},
                {"role": "assistant", "content": '{"tool": "add", "args": {"a": 3, "b": 5}}'},
                {"role": "user", "content": 'tool_result {"tool":"add","result":8}'},
                {"role": "assistant", "content": '{"final": 8}'},
                {"role": "user", "content": user_task},
            ]
            _dump_messages(messages, "init")

            for step in range(1, max_steps + 1):
                _hr(f"STEP {step}  →  CALL LLM")
                request_body = {
                    "system": "<above>",
                    "messages_count": len(messages),
                    "provider": "auto-failover",
                    "temperature": 0,
                    "max_tokens": 256,
                }
                print(f"[llm-req] body summary: {json.dumps(request_body)}")
                print(f"[llm-req] last user msg: {messages[-1]['content']!r}")

                reply = llm.chat(
                    messages=messages,
                    system=system_prompt,
                    temperature=0,
                    max_tokens=256,
                )
                raw = reply["text"]
                print(f"[llm-resp] provider     : {reply.get('provider')}")
                print(f"[llm-resp] model        : {reply.get('model')}")
                print(f"[llm-resp] latency_ms   : {reply.get('latency_ms')}")
                print(f"[llm-resp] in/out tokens: {reply.get('input_tokens')} / {reply.get('output_tokens')}")
                print(f"[llm-resp] attempted    : {reply.get('attempted')}")
                print(f"[llm-resp] raw text     :\n{raw}")

                _hr(f"STEP {step}  →  PARSE")
                parsed = parse_llm_json(raw)
                print(f"[parse]  raw json   : {json.dumps(parsed)}")
                action = normalize_action(parsed)
                print(f"[parse]  normalized: {json.dumps(action)}")

                messages.append({"role": "assistant", "content": json.dumps(action)})

                if "final" in action:
                    _hr(f"STEP {step}  →  FINAL")
                    print(f"[final] model declared answer = {action['final']}")
                    _dump_messages(messages, "final-history")
                    return float(action["final"])

                name = action.get("tool")
                args = action.get("args", {}) or {}
                if name not in tool_names:
                    raise RuntimeError(f"LLM asked for unknown tool: {name!r}")

                # 3. Invoke the tool over MCP
                _hr(f"STEP {step}  →  MCP CALL")
                print(f"[mcp-req] session.call_tool(name={name!r}, args={json.dumps(args)})")
                result = await session.call_tool(name, args)
                print(f"[mcp-resp] isError      : {result.isError}")
                print(f"[mcp-resp] content blocks: {len(result.content)}")
                for j, block in enumerate(result.content):
                    btype = type(block).__name__
                    btext = getattr(block, "text", repr(block))
                    print(f"  [{j}] type={btype}  text={btext!r}")
                tool_text = result.content[0].text if result.content else ""
                print(f"[tool]   {name}({args}) -> {tool_text}")

                tool_msg = f'tool_result {{"tool":"{name}","result":{tool_text}}}'
                print(f"[append] feeding back to LLM as USER message: {tool_msg!r}")
                messages.append({"role": "user", "content": tool_msg})

            raise RuntimeError("agent exceeded max_steps without producing a final answer")


def main() -> None:
    numbers = [10, 20, 30, 40]  # (10+20) + (30-40) = 30 + -10 = 20
    answer = asyncio.run(run_agent(numbers))
    _hr("DONE", ch="═")
    print(f"Final answer: {answer}")


if __name__ == "__main__":
    main()
