"""Entry point for PePeRS MCP Server.

Usage:
    python -m services.mcp
"""

from services.mcp.server import mcp

if __name__ == "__main__":
    mcp.run(transport="sse")
