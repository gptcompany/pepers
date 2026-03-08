"""Step: auto-configure PePeRS MCP server in Claude Desktop / Claude Code."""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path

from rich.console import Console


class McpConfigStep:
    name = "MCP Server -> Claude Desktop"
    description = "Register PePeRS MCP server in Claude config"

    def _config_paths(self) -> list[Path]:
        """Return candidate Claude config paths (Code + Desktop)."""
        home = Path.home()
        paths = [home / ".claude.json"]
        if platform.system() == "Darwin":
            paths.append(
                home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
            )
        elif platform.system() == "Linux":
            paths.append(home / ".config" / "Claude" / "claude_desktop_config.json")
        return paths

    def check(self) -> bool:
        port = os.environ.get("RP_MCP_PORT", "8776")
        expected = f"http://localhost:{port}/sse"
        
        paths = self._config_paths()
        # If any file exists and has the correct config, we consider it ok.
        valid_count = 0
        existing_count = 0
        
        for config_path in paths:
            if not config_path.exists():
                continue
            existing_count += 1
            try:
                config = json.loads(config_path.read_text())
                servers = config.get("mcpServers", {})
                if isinstance(servers, dict):
                    pepers = servers.get("pepers")
                    if isinstance(pepers, dict) and pepers.get("url") == expected:
                        valid_count += 1
            except (json.JSONDecodeError, OSError):
                continue
                
        # Accept partial validity: one correct config is enough.
        return existing_count > 0 and valid_count > 0

    def install(self, console: Console) -> bool:
        port = os.environ.get("RP_MCP_PORT", "8776")
        target_paths = self._config_paths()
        updated_paths: list[Path] = []
        errors: list[str] = []

        for config_path in target_paths:
            if config_path.exists():
                try:
                    text = config_path.read_text()
                    config = json.loads(text) if text.strip() else {}
                except json.JSONDecodeError:
                    msg = f"Cannot parse JSON in {config_path}. File might be corrupted."
                    console.print(f"[yellow]{msg}[/]")
                    errors.append(msg)
                    continue
                except OSError as exc:
                    msg = f"Permission or OS error reading {config_path}: {exc}"
                    console.print(f"[yellow]{msg}[/]")
                    errors.append(msg)
                    continue
                if not isinstance(config, dict):
                    msg = f"Unsupported config format in {config_path} (root is not a dict)."
                    console.print(f"[yellow]{msg}[/]")
                    errors.append(msg)
                    continue
            else:
                config = {}

            servers = config.setdefault("mcpServers", {})
            if not isinstance(servers, dict):
                msg = f"Invalid mcpServers entry in {config_path}. Expected a dict."
                console.print(f"[yellow]{msg}[/]")
                errors.append(msg)
                continue

            servers["pepers"] = {
                "type": "sse",
                "url": f"http://localhost:{port}/sse",
            }

            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_text(json.dumps(config, indent=2) + "\n")
                updated_paths.append(config_path)
            except OSError as exc:
                msg = f"Failed to write {config_path}: {exc}"
                console.print(f"[red]{msg}[/]")
                errors.append(msg)
                continue

        for path in updated_paths:
            console.print(f"[green]Added PePeRS MCP server to {path}[/]")
        
        if updated_paths:
            console.print(f"[dim]URL: http://localhost:{port}/sse[/]")
            if errors:
                console.print(
                    f"[yellow]Completed with warnings ({len(errors)} file(s) skipped).[/]"
                )
            return True
            
        if errors:
            console.print("[yellow]Could not update any Claude configuration files.[/]")
        return False

    def verify(self) -> bool:
        return self.check()
