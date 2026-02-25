"""Step: CLI tool discovery and installation (Node.js, Ollama, LLM CLIs)."""

from __future__ import annotations

import platform
import shutil
import subprocess

from rich.console import Console


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _is_linux() -> bool:
    return platform.system() == "Linux"


def _has_brew() -> bool:
    return shutil.which("brew") is not None


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
            if not _has_brew():
                console.print(
                    "[yellow]Homebrew not found. Install from https://brew.sh[/]"
                )
                return False
            console.print("[cyan]Installing Node.js via Homebrew...[/]")
            cmd = ["brew", "install", "node@20"]
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
            if not _has_brew():
                console.print(
                    "[yellow]Homebrew not found. "
                    "Install Ollama from https://ollama.ai[/]"
                )
                return False
            console.print("[cyan]Installing Ollama via Homebrew...[/]")
            cmd = ["brew", "install", "ollama"]
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
        try:
            subprocess.run(
                ["npm", "install", "-g", self._npm_package],
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
