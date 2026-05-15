# mcp_config.py — External MCP Server Configuration Placeholder
#
# Fill in your external MCP server details here.
# The system will use these when routing specific content types (e.g. YouTube).
# Set `enabled: True` once you have the server details ready.

YOUTUBE_MCP_SERVER = {
    "enabled": False,           # Set to True when you're ready to use it
    "transport": "stdio",
    "command": "docker",
    "args": [
        "run", 
        "-i", 
        "--rm", 
        "mcp/youtube-transcript"
        # "-e", "YOUTUBE_API_KEY",
        # "your-youtube-mcp-image-name"  # Replace with your Docker image name
    ],
    # "env": {
    #     "YOUTUBE_API_KEY": "",  # Your YouTube Data API v3 key
    # },
}

# ── Add more external MCP servers below ───────────────────────────────────

DASHBOARD_MCP_SERVER = {
    "enabled": True,
    "transport": "stdio",
    "command": "python",
    "args": ["/Volumes/lucky-dev/TSAI/AgenticAI/MCP/prefab/05_interactive_talk_to_app_1/server.py"],
}

# Example:
# WEB_SEARCH_MCP_SERVER = {
#     "enabled": False,
#     "transport": "stdio",
#     "command": "npx",
#     "args": ["-y", "@modelcontextprotocol/server-brave-search"],
#     "env": { "BRAVE_API_KEY": "" },
# }
