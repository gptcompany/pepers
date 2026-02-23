"""Step: interactive .env configuration."""

from __future__ import annotations

import os
from pathlib import Path

import questionary
from rich.console import Console

# Config variables with (env_name, description, default, validator)
_CONFIG_VARS: list[tuple[str, str, str, str]] = [
    ("RP_DB_PATH", "SQLite database path", "{root}/data/research.db", "path"),
    ("RP_DATA_DIR", "Data directory", "{root}/data", "path"),
    ("RP_LOG_LEVEL", "Log level", "INFO", "choice:DEBUG,INFO,WARNING,ERROR"),
    ("RP_DISCOVERY_PORT", "Discovery service port", "8770", "port"),
    ("RP_ANALYZER_PORT", "Analyzer service port", "8771", "port"),
    ("RP_EXTRACTOR_PORT", "Extractor service port", "8772", "port"),
    ("RP_VALIDATOR_PORT", "Validator service port", "8773", "port"),
    ("RP_CODEGEN_PORT", "Codegen service port", "8774", "port"),
    ("RP_ORCHESTRATOR_PORT", "Orchestrator service port", "8775", "port"),
    ("RP_MCP_PORT", "MCP server port", "8776", "port"),
    ("RP_DISCOVERY_SOURCES", "Discovery sources (comma-separated)", "arxiv,openalex", "text"),
    ("RP_ORCHESTRATOR_CRON_ENABLED", "Enable cron scheduler", "false", "choice:true,false"),
    ("RP_CAS_URL", "CAS service URL", "http://localhost:8769", "url"),
    ("RP_RAG_URL", "RAG service URL", "http://localhost:8767", "url"),
    ("RP_OLLAMA_URL", "Ollama URL", "http://localhost:11434", "url"),
]


def _validate_port(val: str) -> bool | str:
    try:
        p = int(val)
        if 1 <= p <= 65535:
            return True
        return "Port must be 1-65535"
    except ValueError:
        return "Must be a number"


def _validate_url(val: str) -> bool | str:
    if val.startswith(("http://", "https://")) and ":" in val.split("//", 1)[-1]:
        return True
    return "Must be a valid URL (e.g. http://localhost:8769)"


class EnvConfig:
    name = "Environment configuration (.env)"

    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._env_path = project_root / ".env"

    def check(self) -> bool:
        if not self._env_path.exists():
            return False
        content = self._env_path.read_text()
        # Check that at least the core vars are present
        return "RP_DB_PATH" in content and "RP_DISCOVERY_PORT" in content

    def install(self, console: Console) -> bool:
        console.print("[cyan]Configuring environment variables...[/]")
        console.print(
            "[dim]Press Enter to accept defaults. "
            "API keys are managed separately via dotenvx.[/]\n"
        )

        lines: list[str] = []
        for env_name, description, default, validator in _CONFIG_VARS:
            default_resolved = default.replace("{root}", str(self._root))
            current = os.environ.get(env_name, "")

            if validator.startswith("choice:"):
                choices = validator.split(":", 1)[1].split(",")
                value = questionary.select(
                    f"{description} ({env_name}):",
                    choices=choices,
                    default=current or default_resolved,
                ).ask()
            elif validator == "port":
                value = questionary.text(
                    f"{description} ({env_name}):",
                    default=current or default_resolved,
                    validate=_validate_port,
                ).ask()
            elif validator == "url":
                value = questionary.text(
                    f"{description} ({env_name}):",
                    default=current or default_resolved,
                    validate=_validate_url,
                ).ask()
            else:
                value = questionary.text(
                    f"{description} ({env_name}):",
                    default=current or default_resolved,
                ).ask()

            if value is None:  # user Ctrl-C
                return False
            lines.append(f"{env_name}={value}")

        env_content = "\n".join(lines) + "\n"
        self._env_path.write_text(env_content)
        console.print(f"\n[green]Wrote {self._env_path}[/]")
        return True

    def verify(self) -> bool:
        return self._env_path.exists() and self._env_path.stat().st_size > 0
