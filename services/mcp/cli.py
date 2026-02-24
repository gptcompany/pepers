"""CLI entry point for PePeRS MCP Server.

Used by `uv tool install pepers` to provide the `pepers-mcp` command.

Usage:
    pepers-mcp                              # Start MCP server with SSE transport
    pepers-mcp --port 8776                  # Custom port
    pepers-mcp --flavor plain               # Disable arcade messages
    pepers-mcp --transport streamable-http  # Use Streamable HTTP transport
"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    """Start PePeRS MCP Server from CLI."""
    parser = argparse.ArgumentParser(
        prog="pepers-mcp",
        description="PePeRS MCP Server — SSE interface for Claude Desktop/Cursor",
    )
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("RP_MCP_PORT", "8776")),
        help="SSE server port (default: 8776, env: RP_MCP_PORT)",
    )
    parser.add_argument(
        "--flavor", choices=["arcade", "plain"],
        default=os.environ.get("RP_MCP_FLAVOR", "arcade"),
        help="Output flavor: arcade (Metal Slug!) or plain (default: arcade)",
    )
    parser.add_argument(
        "--orchestrator-url",
        default=os.environ.get("RP_ORCHESTRATOR_URL", "http://localhost:8775"),
        help="Orchestrator URL (default: http://localhost:8775)",
    )
    parser.add_argument(
        "--transport", choices=["sse", "streamable-http"],
        default=os.environ.get("RP_MCP_TRANSPORT", "sse"),
        help="Transport: sse (default) or streamable-http",
    )
    args = parser.parse_args()

    # Set env vars before importing server (reads them at import time)
    os.environ["RP_MCP_PORT"] = str(args.port)
    os.environ["RP_MCP_FLAVOR"] = args.flavor
    os.environ["RP_ORCHESTRATOR_URL"] = args.orchestrator_url

    # Import after setting env vars
    from services.mcp.server import mcp

    print(f"\U0001f438\U0001f52b MISSION START! PePeRS MCP Server on :{args.port} — LFG!")
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
