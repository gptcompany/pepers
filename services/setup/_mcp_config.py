"""Step: auto-configure PePeRS MCP server in Claude Desktop / Claude Code."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

from rich.console import Console


class McpConfigStep:
    name = "MCP Server -> Claude Code/Desktop"
    description = "Register PePeRS MCP server in selected Claude clients"
    auto_reconcile_when_configured = True

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

    def _code_config_path(self) -> Path:
        return Path.home() / ".claude.json"

    def _desktop_config_path(self) -> Path:
        home = Path.home()
        if platform.system() == "Darwin":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        return home / ".config" / "Claude" / "claude_desktop_config.json"

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
        try:
            import questionary
        except Exception:
            questionary = None

        port = os.environ.get("RP_MCP_PORT", "8776")
        url = f"http://localhost:{port}/sse"
        target_paths: list[Path]

        code_path = self._code_config_path()
        desktop_path = self._desktop_config_path()
        if questionary is None:
            target_paths = self._config_paths()
            want_code = True
        else:
            choices = [
                questionary.Choice("Claude Code", value="code", checked=True),
                questionary.Choice("Claude Desktop", value="desktop", checked=True),
            ]
            try:
                selected = questionary.checkbox(
                    "Select Claude clients to configure MCP:",
                    choices=choices,
                ).ask()
            except EOFError:
                selected = ["code", "desktop"]
            if not selected:
                console.print("[yellow]No client selected, skipping MCP configuration.[/]")
                return False
            want_code = "code" in selected
            want_desktop = "desktop" in selected
            target_paths = []
            if want_code:
                target_paths.append(code_path)
            if want_desktop:
                target_paths.append(desktop_path)

        cli_ok = self._install_with_claude_cli(console, url) if want_code else False
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
                "url": url,
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
            console.print(f"[dim]URL: {url}[/]")
            if errors:
                console.print(
                    f"[yellow]Completed with warnings ({len(errors)} file(s) skipped).[/]"
                )
            return True
            
        if cli_ok:
            console.print(
                "[yellow]Claude CLI MCP add succeeded, but no config file could be updated locally.[/]"
            )
            return True

        if errors:
            console.print("[yellow]Could not update any Claude configuration files.[/]")
        return False

    def _install_with_claude_cli(self, console: Console, url: str) -> bool:
        """Try built-in Claude MCP command first."""
        if not self._ensure_claude_clients(console):
            return False
        cmd = [
            "claude",
            "mcp",
            "add",
            "--scope",
            "user",
            "--transport",
            "sse",
            "pepers",
            url,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            console.print(f"[yellow]Claude MCP CLI add skipped:[/] {exc}")
            return False

        if result.returncode == 0:
            console.print("[green]Configured MCP via Claude CLI built-in command.[/]")
            return True

        stderr = (result.stderr or "").strip().lower()
        # If already present, we still consider CLI path effective.
        if "already" in stderr and "exists" in stderr:
            console.print("[dim]Claude CLI MCP entry already exists.[/]")
            return True

        console.print(
            f"[yellow]Claude CLI MCP add failed (continuing with file fallback):[/] "
            f"{(result.stderr or result.stdout or '').strip()[:200]}"
        )
        return False

    def _ensure_claude_clients(self, console: Console) -> bool:
        """If Claude tools are missing, offer native install choices."""
        if shutil.which("claude") is not None:
            return True

        try:
            import questionary
        except Exception:
            console.print("[yellow]Claude CLI not found and interactive installer unavailable.[/]")
            return False

        console.print("[yellow]Claude Code CLI not detected.[/]")
        if not questionary.confirm(
            "Install Claude Code CLI now?",
            default=True,
        ).ask():
            return False

        installed = False
        if shutil.which("npm") is not None:
            cmd = ["npm", "install", "-g", "@anthropic-ai/claude-code"]
            if platform.system() == "Darwin" and shutil.which("port"):
                cmd = ["sudo"] + cmd
            try:
                subprocess.run(cmd, check=True, text=True)
                installed = shutil.which("claude") is not None
            except subprocess.CalledProcessError:
                installed = False

        if not installed:
            console.print(
                "[yellow]Could not auto-install Claude Code CLI.[/]\n"
                "Install manually: npm install -g @anthropic-ai/claude-code"
            )
            return False

        if platform.system() == "Darwin":
            desktop_path = Path.home() / "Applications" / "Claude.app"
            system_desktop = Path("/Applications/Claude.app")
            if not desktop_path.exists() and not system_desktop.exists():
                if questionary.confirm(
                    "Claude Desktop not detected. Install Claude Desktop now?",
                    default=False,
                ).ask():
                    if shutil.which("brew"):
                        try:
                            subprocess.run(
                                ["brew", "install", "--cask", "claude"],
                                check=True,
                                text=True,
                            )
                        except subprocess.CalledProcessError:
                            console.print(
                                "[yellow]Auto-install Claude Desktop failed.[/]\n"
                                "Install manually from https://claude.ai/download"
                            )
                    else:
                        console.print(
                            "[yellow]Homebrew not found.[/]\n"
                            "Install Claude Desktop manually from https://claude.ai/download"
                        )

        return True

    def verify(self) -> bool:
        return self.check()
