"""
Agentic loop over example_mcp_server.py using Gemini.

The model picks tools from the MCP server and we execute them, feeding results
back into the prompt until it emits FINAL_ANSWER. A 5s sleep is inserted before
each LLM call so students can watch the loop unfold.

Task chosen on purpose so the model needs ~3 tools:
  1. write_file  — create a file in the sandbox
  2. read_file   — verify what was written
  3. edit_file   — replace a word inside that file

Run:
  # from NewCode/
  uv run AgenticMCPUse.py
  # or: python AgenticMCPUse.py

Env:
  GEMINI_API_KEY in a .env file (same as before)
"""

import asyncio
import os
from concurrent.futures import TimeoutError

from dotenv import load_dotenv
from google import genai
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

MODEL = "gemini-3.1-flash-lite-preview"   # per your instruction; swap if the name differs
MAX_ITERATIONS = 6
LLM_SLEEP_SECONDS = 5
LLM_TIMEOUT = 15

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


async def generate_with_timeout(prompt: str, timeout: int = LLM_TIMEOUT):
    """Run the blocking Gemini call in a thread with a timeout."""
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: client.models.generate_content(model=MODEL, contents=prompt),
        ),
        timeout=timeout,
    )


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
        return eval(value)       # teaching code; fine inside the sandbox
    if schema_type == "boolean":
        return value.lower() in ("true", "1", "yes")
    return value


async def main():
    server_params = StdioServerParameters(
        command="python",
        args=["example_mcp_server.py"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected to example_mcp_server")

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
                    response = await generate_with_timeout(prompt)
                except (TimeoutError, asyncio.TimeoutError):
                    print("LLM timed out — stopping.")
                    break
                except Exception as e:
                    print(f"LLM error: {e}")
                    break

                text = (response.text or "").strip().splitlines()[0].strip()
                print(f"LLM: {text}")

                if text.startswith("FINAL_ANSWER:"):
                    print("\n=== Agent done ===")
                    print(text)
                    break

                if not text.startswith("FUNCTION_CALL:"):
                    print("Unexpected response format — stopping.")
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
