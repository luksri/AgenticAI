"""
Agentic loop over example_mcp_server.py — LOCAL version using Ollama.

Same structure as AgenticMCPUse.py. The ONLY real difference is the LLM
call: instead of Gemini, we hit a local Ollama server. Everything else —
tool discovery, FUNCTION_CALL/FINAL_ANSWER protocol, 5s pacing, loop —
is identical, to drive home the point that "the router can be any LLM".

Setup:
  1. Install Ollama           https://ollama.com
  2. Pull the model           ollama pull gemma4:26b
  3. Start the server         ollama serve
  4. Install deps             pip install requests python-dotenv mcp

Run (from NewCode/):
  python AgenticMCPUsageOllama.py

Env (optional, via .env):
  OLLAMA_HOST=http://localhost:11434
  OLLAMA_MODEL=gemma4:26b
"""

import asyncio
import os

import requests
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:26b")

MAX_ITERATIONS = 6
LLM_SLEEP_SECONDS = 0
LLM_TIMEOUT = 180   # local inference can be slow on big models


def call_ollama(prompt: str) -> str:
    """Blocking call to Ollama's /api/generate, returns the raw text."""
    try:
        r = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=LLM_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["response"]
    except requests.ConnectionError:
        raise RuntimeError(
            f"Can't reach Ollama at {OLLAMA_HOST}. Is it running? Try: ollama serve"
        )
    except requests.HTTPError as e:
        raise RuntimeError(
            f"Ollama API error: {e}. Did you pull the model? Try: ollama pull {OLLAMA_MODEL}"
        )


async def generate(prompt: str) -> str:
    """Run the blocking Ollama call in a thread so the event loop stays free."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, call_ollama, prompt)


def describe_tools(tools) -> str:
    lines = []
    for i, t in enumerate(tools, 1):
        props = (t.inputSchema or {}).get("properties", {})
        params = ", ".join(f"{n}: {p.get('type', '?')}" for n, p in props.items()) or "no params"
        lines.append(f"{i}. {t.name}({params}) — {t.description or ''}")
    return "\n".join(lines)


def coerce(value: str, schema_type: str):
    if schema_type == "integer":
        return int(value)
    if schema_type == "number":
        return float(value)
    if schema_type == "array":
        return eval(value)
    if schema_type == "boolean":
        return value.lower() in ("true", "1", "yes")
    return value


def first_directive(text: str) -> str:
    """Pick the first line that looks like our protocol (FUNCTION_CALL / FINAL_ANSWER).
    Local models sometimes pad with extra prose; this keeps the parser robust.
    """
    for line in (text or "").splitlines():
        s = line.strip().lstrip("`").lstrip()
        if s.startswith("FUNCTION_CALL:") or s.startswith("FINAL_ANSWER:"):
            return s
    return (text or "").strip()


async def main():
    server_params = StdioServerParameters(
        command="python",
        args=["example_mcp_server.py"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"Connected to example_mcp_server — routing via Ollama ({OLLAMA_MODEL})")

            tools = (await session.list_tools()).tools
            tools_desc = describe_tools(tools)
            print(f"Loaded {len(tools)} tools\n")

            system_prompt = f"""You are a file-manipulation agent working inside a sandboxed MCP server.
You solve tasks by calling tools ONE AT A TIME and observing their results.

Available tools:
{tools_desc}

Respond with EXACTLY ONE line, in one of these two formats:
  FUNCTION_CALL: tool_name|arg1|arg2|...
  FINAL_ANSWER: <short natural-language summary of what you did>

Rules:
- Output only the single directive line. No prose, no markdown, no code fences.
- Provide args in the exact order of the tool's parameters.
- Do not invent tools that are not listed above.
- After each FUNCTION_CALL you'll receive the result; use it to decide the next step.
- Prefer the simplest 2–3 tool sequence that solves the task.
- When the task is complete, emit FINAL_ANSWER.
"""

            task = (
                "Create a file called greeting.txt in the sandbox with the content "
                "'hello rohan'. Then read it back to confirm. Then edit it so "
                "'hello' becomes 'hi'. Finally give a FINAL_ANSWER."
            )

            history: list[str] = []
            for iteration in range(1, MAX_ITERATIONS + 1):
                print(f"\n--- Iteration {iteration} ---")

                context = "\n".join(history) if history else "(no prior steps)"
                prompt = (
                    f"{system_prompt}\n"
                    f"Task: {task}\n\n"
                    f"Previous steps:\n{context}\n\n"
                    f"What is your next single action?"
                )

                print(f"Sleeping {LLM_SLEEP_SECONDS}s before LLM call...")
                await asyncio.sleep(LLM_SLEEP_SECONDS)

                try:
                    raw = await generate(prompt)
                except Exception as e:
                    print(f"Ollama error: {e}")
                    break

                text = first_directive(raw)
                print(f"LLM: {text}")

                if text.startswith("FINAL_ANSWER:"):
                    print("\n=== Agent done ===")
                    print(text)
                    break

                if not text.startswith("FUNCTION_CALL:"):
                    print("Unexpected response format — stopping.")
                    print(f"Raw model output:\n{raw}")
                    break

                _, call = text.split(":", 1)
                parts = [p.strip() for p in call.split("|")]
                func_name, raw_args = parts[0], parts[1:]

                tool = next((t for t in tools if t.name == func_name), None)
                if tool is None:
                    msg = f"Unknown tool {func_name!r}"
                    print(msg)
                    history.append(f"Iteration {iteration}: {msg}")
                    continue

                props = (tool.inputSchema or {}).get("properties", {})
                arguments = {
                    name: coerce(val, info.get("type", "string"))
                    for (name, info), val in zip(props.items(), raw_args)
                }

                print(f"→ {func_name}({arguments})")
                try:
                    result = await session.call_tool(func_name, arguments=arguments)
                    payload = (
                        result.content[0].text
                        if result.content and hasattr(result.content[0], "text")
                        else str(result)
                    )
                except Exception as e:
                    payload = f"ERROR: {e}"

                print(f"← {payload}")
                history.append(
                    f"Iteration {iteration}: called {func_name}({arguments}) → {payload}"
                )
            else:
                print("\nReached MAX_ITERATIONS without FINAL_ANSWER.")


if __name__ == "__main__":
    asyncio.run(main())
