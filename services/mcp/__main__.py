"""Entry point for PePeRS MCP Server.

Usage:
    python -m services.mcp
"""

import os

from services.mcp.server import mcp

if __name__ == "__main__":
    transport = os.environ.get("RP_MCP_TRANSPORT", "sse")
    mcp.run(transport=transport)
