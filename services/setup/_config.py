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
    ("PEPERS_DATA_DIR", "Docker data mount path (absolute recommended)", "{root}/data", "path"),
    ("RP_LOG_LEVEL", "Log level", "INFO", "choice:DEBUG,INFO,WARNING,ERROR"),
    ("RP_DISCOVERY_PORT", "Discovery service port", "8770", "port"),
    ("RP_ANALYZER_PORT", "Analyzer service port", "8771", "port"),
    ("RP_EXTRACTOR_PORT", "Extractor service port", "8772", "port"),
    ("RP_VALIDATOR_PORT", "Validator service port", "8773", "port"),
    ("RP_CODEGEN_PORT", "Codegen service port", "8774", "port"),
    ("RP_ORCHESTRATOR_PORT", "Orchestrator service port", "8775", "port"),
    ("RP_MCP_PORT", "MCP server port", "8776", "port"),
    ("RP_DISCOVERY_SOURCES", "Discovery sources (comma-separated)", "arxiv", "text"),
    ("RP_ANALYZER_THRESHOLD", "Analyzer relevance threshold", "0.7", "text"),
    ("RP_ANALYZER_MAX_PAPERS", "Analyzer max papers per batch", "10", "text"),
    ("RP_EXTRACTOR_MAX_PAPERS", "Extractor max papers per batch", "10", "text"),
    ("RP_ORCHESTRATOR_CRON_ENABLED", "Enable cron scheduler", "false", "choice:true,false"),
    ("RP_ORCHESTRATOR_CRON", "Orchestrator cron expression", "0 8 * * *", "text"),
    ("RP_ORCHESTRATOR_STAGES_PER_RUN", "Orchestrator stages per run", "5", "text"),
    (
        "RP_ORCHESTRATOR_DEFAULT_QUERY",
        "Orchestrator default discovery query",
        'abs:"Kelly criterion" AND cat:q-fin.*',
        "text",
    ),
    ("RP_VALIDATOR_CAS_URL", "CAS service URL (validator)", "http://localhost:8769", "url"),
    ("RP_VALIDATOR_MAX_FORMULAS", "Validator max formulas per batch", "50", "text"),
    ("RP_VALIDATOR_ENGINES", "Validator engines (comma-separated)", "sympy,sage", "text"),
    ("RP_EXTRACTOR_RAG_URL", "RAG service URL (extractor)", "http://localhost:8767", "url"),
    ("RP_RAG_QUERY_URL", "RAG query URL (orchestrator)", "http://localhost:8767", "url"),
    ("RP_CODEGEN_OLLAMA_URL", "Ollama URL (codegen)", "http://localhost:11434", "url"),
    ("RP_CODEGEN_MAX_FORMULAS", "Codegen max formulas per batch", "50", "text"),
    ("RP_MCP_FLAVOR", "MCP output flavor", "arcade", "choice:arcade,plain"),
]


def _read_env_values(path: Path) -> dict[str, str]:
    """Parse a simple .env file into a dict.

    Supports KEY=value lines and ignores comments/blank lines.
    """
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


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
    description = "Core service ports, URLs, defaults, and orchestration settings"

    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._env_path = project_root / ".env"

    def check(self) -> bool:
        if not self._env_path.exists():
            return False
        content = self._env_path.read_text()
        required = (
            "RP_DB_PATH",
            "RP_DISCOVERY_PORT",
            "RP_VALIDATOR_CAS_URL",
            "RP_EXTRACTOR_RAG_URL",
            "RP_CODEGEN_OLLAMA_URL",
        )
        return all(f"{key}=" in content for key in required)

    def install(self, console: Console) -> bool:
        console.print("[cyan]Configuring environment variables...[/]")
        console.print(
            "[dim]Press Enter to accept defaults. "
            "API keys are managed separately via dotenvx.[/]\n"
        )

        existing_values = _read_env_values(self._env_path)
        lines: list[str] = []
        for env_name, description, default, validator in _CONFIG_VARS:
            default_resolved = default.replace("{root}", str(self._root))
            current = existing_values.get(env_name) or os.environ.get(env_name, "")

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

        if questionary.confirm(
            "Add custom environment variables?",
            default=False,
        ).ask():
            while True:
                key = questionary.text("Variable name (empty to finish):").ask()
                if key is None:
                    return False
                key = key.strip()
                if not key:
                    break
                value = questionary.text(f"Value for {key}:").ask()
                if value is None:
                    return False
                lines.append(f"{key}={value}")

        env_content = "\n".join(lines) + "\n"
        self._env_path.write_text(env_content)
        console.print(f"\n[green]Wrote {self._env_path}[/]")
        return True

    def verify(self) -> bool:
        return self._env_path.exists() and self._env_path.stat().st_size > 0
