"""Entry point for PePeRS MCP Server.

Usage:
    python -m services.mcp
"""

import os
from typing import Literal, cast

from services.mcp.server import mcp

if __name__ == "__main__":
    transport = os.environ.get("RP_MCP_TRANSPORT", "sse")
    if transport not in {"stdio", "sse", "streamable-http"}:
        transport = "sse"
    transport_name = cast(Literal["stdio", "sse", "streamable-http"], transport)
    mcp.run(transport=transport_name)
