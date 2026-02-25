"""Step: auto-configure PePeRS MCP server in Claude Desktop / Claude Code."""

from __future__ import annotations

import json
import os
from pathlib import Path

from rich.console import Console


class McpConfigStep:
    name = "MCP Server -> Claude Desktop"
    description = "Register PePeRS MCP server in Claude config"

    def _config_path(self) -> Path:
        """Find the preferred Claude config file path.

        We currently write to ~/.claude.json (Claude Code) for portability.
        """
        candidates = [
            Path.home() / ".claude.json",
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]

    def check(self) -> bool:
        config_path = self._config_path()
        if not config_path.exists():
            return False
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            return False

        servers = config.get("mcpServers", {})
        if not isinstance(servers, dict):
            return False
        pepers = servers.get("pepers")
        if not isinstance(pepers, dict):
            return False
        port = os.environ.get("RP_MCP_PORT", "8776")
        return pepers.get("url") == f"http://localhost:{port}/sse"

    def install(self, console: Console) -> bool:
        config_path = self._config_path()

        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                console.print(f"[red]Cannot parse {config_path}[/]")
                return False
            if not isinstance(config, dict):
                console.print(f"[red]Unsupported config format in {config_path}[/]")
                return False
        else:
            config = {}

        port = os.environ.get("RP_MCP_PORT", "8776")
        servers = config.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            console.print(f"[red]Invalid mcpServers entry in {config_path}[/]")
            return False

        servers["pepers"] = {
            "type": "sse",
            "url": f"http://localhost:{port}/sse",
        }

        try:
            config_path.write_text(json.dumps(config, indent=2) + "\n")
        except OSError as exc:
            console.print(f"[red]Failed to write {config_path}:[/] {exc}")
            return False

        console.print(f"[green]Added PePeRS MCP server to {config_path}[/]")
        console.print(f"[dim]URL: http://localhost:{port}/sse[/]")
        return True

    def verify(self) -> bool:
        return self.check()
