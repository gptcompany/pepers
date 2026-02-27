"""Step: CLI tool discovery and installation (Node.js, Ollama, LLM CLIs)."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import urllib.request
from pathlib import Path

from rich.console import Console


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _is_linux() -> bool:
    return platform.system() == "Linux"


def _has_port() -> bool:
    return shutil.which("port") is not None


_MACOS_NAMES: dict[int, str] = {
    12: "12-Monterey",
    13: "13-Ventura",
    14: "14-Sonoma",
    15: "15-Sequoia",
    16: "16-Tahoe",
}


def _ensure_macports(console: Console) -> bool:
    """Ensure MacPorts is available, auto-installing if needed."""
    if _has_port():
        return True

    ver = platform.mac_ver()[0]
    major = int(ver.split(".")[0])
    os_label = _MACOS_NAMES.get(major)
    if not os_label:
        console.print(
            f"[yellow]macOS {major} not mapped for MacPorts auto-install.[/]\n"
            "Install manually from https://www.macports.org/install.php"
        )
        return False

    # Resolve latest MacPorts version from GitHub releases
    mp_version = "2.10.5"
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/macports/macports-base/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        mp_version = data["tag_name"].lstrip("v")
    except Exception:
        pass  # fallback to hardcoded version

    pkg_name = f"MacPorts-{mp_version}-{os_label}.pkg"
    url = (
        f"https://github.com/macports/macports-base/releases/"
        f"download/v{mp_version}/{pkg_name}"
    )
    tmp_pkg = Path(f"/tmp/{pkg_name}")

    console.print(f"[cyan]Installing MacPorts {mp_version} for macOS {os_label}...[/]")
    try:
        subprocess.run(
            ["curl", "-fsSL", "-o", str(tmp_pkg), url],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError:
        console.print(
            "[yellow]MacPorts download failed.[/]\n"
            "Install manually from https://www.macports.org/install.php"
        )
        return False

    try:
        subprocess.run(
            ["sudo", "installer", "-pkg", str(tmp_pkg), "-target", "/"],
            check=True, text=True,
        )
    except subprocess.CalledProcessError:
        console.print("[red]MacPorts installation failed.[/]")
        return False
    finally:
        tmp_pkg.unlink(missing_ok=True)

    # Ensure /opt/local/bin is in PATH for this process
    path = os.environ.get("PATH", "")
    if "/opt/local/bin" not in path:
        os.environ["PATH"] = f"/opt/local/bin:/opt/local/sbin:{path}"

    return shutil.which("port") is not None


class NodeCheck:
    name = "Node.js >= 18"
    description = "Required for Claude CLI, Gemini CLI, Codex CLI"

    def check(self) -> bool:
        if not shutil.which("node"):
            return False
        try:
            result = subprocess.run(
                ["node", "--version"],
                capture_output=True, text=True,
            )
            major = int(result.stdout.strip().lstrip("v").split(".")[0])
            return major >= 18
        except Exception:
            return False

    def install(self, console: Console) -> bool:
        if _is_macos():
            if not _ensure_macports(console):
                return False
            console.print("[cyan]Installing Node.js via MacPorts...[/]")
            cmd = ["sudo", "port", "install", "nodejs20"]
        elif _is_linux():
            console.print("[cyan]Installing Node.js via nodesource...[/]")
            cmd = [
                "sh", "-c",
                "curl -fsSL https://deb.nodesource.com/setup_20.x | "
                "sudo -E bash - && sudo apt-get install -y nodejs",
            ]
        else:
            console.print(
                "[yellow]Unsupported platform. "
                "Install Node.js from https://nodejs.org[/]"
            )
            return False
        try:
            subprocess.run(cmd, check=True, text=True)
            return True
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]Install failed:[/] {exc}")
            return False

    def verify(self) -> bool:
        return self.check()


class OllamaCheck:
    name = "Ollama"
    description = "Local LLM server for codegen and analysis"

    def check(self) -> bool:
        return shutil.which("ollama") is not None

    def install(self, console: Console) -> bool:
        if _is_macos():
            if not _ensure_macports(console):
                return False
            console.print("[cyan]Installing Ollama via MacPorts...[/]")
            cmd = ["sudo", "port", "install", "ollama"]
        elif _is_linux():
            console.print("[cyan]Installing Ollama...[/]")
            cmd = ["sh", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"]
        else:
            console.print(
                "[yellow]Install Ollama from https://ollama.ai[/]"
            )
            return False
        try:
            subprocess.run(cmd, check=True, text=True)
            return True
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]Install failed:[/] {exc}")
            return False

    def verify(self) -> bool:
        return self.check()


class NpmCliTool:
    """Generic step for npm-installed CLI tools."""

    def __init__(
        self,
        name: str,
        description: str,
        binary: str,
        npm_package: str,
    ) -> None:
        self.name = name
        self.description = description
        self._binary = binary
        self._npm_package = npm_package

    def check(self) -> bool:
        return shutil.which(self._binary) is not None

    def install(self, console: Console) -> bool:
        if not shutil.which("npm"):
            console.print(
                "[yellow]npm not found. Install Node.js first.[/]"
            )
            return False
        console.print(f"[cyan]Installing {self._npm_package}...[/]")
        # MacPorts Node.js requires sudo for global npm installs
        cmd = ["npm", "install", "-g", self._npm_package]
        if _is_macos():
            cmd = ["sudo"] + cmd
        try:
            subprocess.run(
                cmd,
                check=True, capture_output=True, text=True,
            )
            return True
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]npm install failed:[/] {exc}")
            return False

    def verify(self) -> bool:
        return self.check()


def get_all_steps() -> list:
    return [
        NodeCheck(),
        OllamaCheck(),
        NpmCliTool(
            "Claude CLI",
            "Anthropic Claude for LLM fallback chain",
            "claude",
            "@anthropic-ai/claude-code",
        ),
        NpmCliTool(
            "Gemini CLI",
            "Google Gemini for LLM fallback chain",
            "gemini",
            "@google/gemini-cli",
        ),
        NpmCliTool(
            "Codex CLI",
            "OpenAI Codex for LLM fallback chain",
            "codex",
            "@openai/codex",
        ),
    ]
