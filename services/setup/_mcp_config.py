"""Step: auto-configure PePeRS MCP server in Claude Desktop / Claude Code."""

from __future__ import annotations

import json
import os
from pathlib import Path

from rich.console import Console


class McpConfigStep:
    name = "MCP Server -> Claude Desktop"
    description = "Register PePeRS MCP server in Claude config"

    def _config_paths(self) -> list[Path]:
        """Return candidate Claude config paths (Code + Desktop)."""
        home = Path.home()
        paths = [home / ".claude.json"]
        if os.name == "posix":
            # Claude Desktop on macOS
            paths.append(
                home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
            )
            # Claude Desktop on Linux
            paths.append(home / ".config" / "Claude" / "claude_desktop_config.json")
        return paths

    def _existing_or_default_paths(self) -> list[Path]:
        paths = self._config_paths()
        existing = [p for p in paths if p.exists()]
        if existing:
            return existing
        return [paths[0]]

    def check(self) -> bool:
        port = os.environ.get("RP_MCP_PORT", "8776")
        expected = f"http://localhost:{port}/sse"
        for config_path in self._config_paths():
            if not config_path.exists():
                continue
            try:
                config = json.loads(config_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            servers = config.get("mcpServers", {})
            if not isinstance(servers, dict):
                continue
            pepers = servers.get("pepers")
            if isinstance(pepers, dict) and pepers.get("url") == expected:
                return True
        return False

    def install(self, console: Console) -> bool:
        port = os.environ.get("RP_MCP_PORT", "8776")
        target_paths = self._existing_or_default_paths()
        updated_paths: list[Path] = []

        for config_path in target_paths:
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

            servers = config.setdefault("mcpServers", {})
            if not isinstance(servers, dict):
                console.print(f"[red]Invalid mcpServers entry in {config_path}[/]")
                return False

            servers["pepers"] = {
                "type": "sse",
                "url": f"http://localhost:{port}/sse",
            }

            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_text(json.dumps(config, indent=2) + "\n")
            except OSError as exc:
                console.print(f"[red]Failed to write {config_path}:[/] {exc}")
                return False
            updated_paths.append(config_path)

        for path in updated_paths:
            console.print(f"[green]Added PePeRS MCP server to {path}[/]")
        console.print(f"[dim]URL: http://localhost:{port}/sse[/]")
        return bool(updated_paths)

    def verify(self) -> bool:
        return self.check()
