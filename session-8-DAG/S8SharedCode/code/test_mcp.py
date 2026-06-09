import asyncio
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    MCP_SERVER = Path("mcp_server.py").resolve()
    server_params = StdioServerParameters(command=sys.executable, args=[str(MCP_SERVER)])
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as mcp:
                await mcp.initialize()
                print("MCP Initialized!")
    except Exception as e:
        print(f"Exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
