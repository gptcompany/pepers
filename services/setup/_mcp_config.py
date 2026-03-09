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
        port = self._resolved_mcp_port()
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
                    if isinstance(pepers, dict) and self._entry_matches(pepers, expected):
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

        if not self._health_gate_ok():
            console.print(
                "[yellow]PePeRS health is not green yet.[/]\n"
                "Run Docker reconcile and the aggregated health check first, "
                "then configure MCP clients."
            )
            return False

        port = self._resolved_mcp_port()
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
                questionary.Choice("Claude Desktop", value="desktop", checked=False),
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
            is_desktop = config_path == desktop_path
            if is_desktop and not self._ensure_npx_for_desktop(console):
                msg = (
                    "Claude Desktop MCP bridge requires 'npx' "
                    "(Node.js/npm not detected)."
                )
                console.print(f"[yellow]{msg} Skipping Desktop config.[/]")
                errors.append(msg)
                continue
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

            servers["pepers"] = self._build_pepers_entry(
                url=url,
                for_desktop=is_desktop,
            )

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

    def _health_gate_ok(self) -> bool:
        try:
            from services.setup._verify import AggregatedHealthCheck
        except Exception:
            return False
        return AggregatedHealthCheck().verify()

    def _ensure_npx_for_desktop(self, console: Console) -> bool:
        if shutil.which("npx") is not None:
            return True
        console.print(
            "[yellow]npx not found. Installing Node.js automatically for Claude Desktop MCP...[/]"
        )
        try:
            from services.setup._cli_tools import NodeCheck
        except Exception as exc:
            console.print(f"[yellow]Cannot load Node installer:[/] {exc}")
            return False

        node_step = NodeCheck()
        if not node_step.check():
            if not node_step.install(console):
                return False
        return shutil.which("npx") is not None

    def _resolved_mcp_port(self) -> str:
        port = os.environ.get("RP_MCP_PORT", "").strip()
        if port:
            return port
        env_path = Path.cwd() / ".env"
        if not env_path.exists():
            return "8776"
        try:
            for raw_line in env_path.read_text().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == "RP_MCP_PORT":
                    candidate = value.strip()
                    if candidate:
                        return candidate
        except OSError:
            pass
        return "8776"

    def _build_pepers_entry(self, *, url: str, for_desktop: bool) -> dict:
        # Claude Desktop can reject direct SSE entries on some builds; prefer stdio bridge.
        if for_desktop:
            return {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "mcp-remote", "--sse", url],
            }
        return {
            "type": "sse",
            "url": url,
        }

    def _entry_matches(self, entry: dict, expected_url: str) -> bool:
        # Direct SSE form
        if entry.get("url") == expected_url:
            return True
        # Desktop stdio bridge form
        command = str(entry.get("command", "")).strip().lower()
        if command != "npx":
            return False
        args = entry.get("args")
        if not isinstance(args, list):
            return False
        normalized = [str(a).strip().lower() for a in args]
        if "mcp-remote" not in normalized:
            return False
        return any(str(a).strip() == expected_url for a in args)

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
