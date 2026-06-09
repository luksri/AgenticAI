import asyncio
from skills import SkillRegistry
from gateway import LLM
from mcp_runner import run_with_tools

async def main():
    reg = SkillRegistry()
    skill = reg.get("retriever")
    try:
        reply = await run_with_tools(
            prompt="Hello",
            tools_payload=[{"name": "search_knowledge", "description": "...", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}],
            agent=skill.name,
            session_id="test-123",
            provider_pin=skill.provider_pin,
            max_tokens=skill.max_tokens,
            temperature=skill.temperature,
        )
        print("Reply:", reply)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
