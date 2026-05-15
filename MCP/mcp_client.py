from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import asyncio


async def main():
    server_params = StdioServerParameters(
        command="python",
        args=["mcp_server.py"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected to MCP server")

            text = input("Enter text to reverse: ")

            result = await session.call_tool(
                "reverse_string",
                arguments={"text": text},
            )

            reversed_text = result.content[0].text
            print(f"Reversed text: {reversed_text}")

            print("\n--- Available tools ---")
            tools = (await session.list_tools()).tools
            for t in tools:
                print(f"- {t.name}: {t.description}")
            
            

if __name__ == "__main__":
    asyncio.run(main()) 