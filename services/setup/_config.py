"""Step: interactive .env configuration."""

from __future__ import annotations

import os
import socket
import sys
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

import questionary
from rich.console import Console

# Config variables with (env_name, description, default, validator)
_CONFIG_VARS: list[tuple[str, str, str, str]] = [
    ("RP_DB_PATH", "SQLite database path", "{root}/data/research.db", "path"),
    ("RP_DATA_DIR", "Data directory", "{root}/data", "path"),
    ("PEPERS_DATA_DIR", "Docker data mount path (absolute recommended)", "{root}/data", "path"),
    ("PEPERS_PROJECT_HOST_DIR", "Host path to the pepers repo root", "{root}", "path"),
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
    ("RP_MAX_FORMULAS_DEFAULT", "Default max formulas per batch", "100", "text"),
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
    ("RP_VALIDATOR_ENGINES", "Validator engines (comma-separated)", "sympy,sage", "text"),
    ("RP_EXTRACTOR_RAG_URL", "RAG service URL (extractor)", "http://localhost:8767", "url"),
    ("RP_RAG_QUERY_URL", "RAG query URL (orchestrator)", "http://localhost:8767", "url"),
    ("RP_CODEGEN_OLLAMA_URL", "Ollama URL (codegen)", "http://localhost:11434", "url"),
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


def _print_env_hint(console: Console, env_path: Path) -> None:
    console.print(f"[dim].env path:[/] {env_path}")
    if sys.platform == "darwin":
        console.print(f"[dim]Open in TextEdit:[/] open -e \"{env_path}\"")
        console.print(f"[dim]Open in VS Code:[/] code \"{env_path}\"")
    else:
        console.print(f"[dim]Open in editor:[/] $EDITOR \"{env_path}\"")


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
            "PEPERS_PROJECT_HOST_DIR",
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
        _print_env_hint(console, self._env_path)
        console.print()

        existing_values = _read_env_values(self._env_path)
        config_values: dict[str, str] = {}
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
            config_values[env_name] = value

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
                config_values[key] = value

        changed = self._auto_resolve_internal_port_conflicts(config_values, console)

        env_content = "\n".join(f"{k}={v}" for k, v in config_values.items()) + "\n"
        self._env_path.write_text(env_content)
        console.print(f"\n[green]Wrote {self._env_path}[/]")
        _print_env_hint(console, self._env_path)
        if changed:
            self._reconcile_services_after_port_change(console)
        return True

    def install_defaults(self, console: Console) -> bool:
        """Non-interactive install: write .env with safe defaults.

        Merges over any existing values — existing keys are preserved.
        """
        existing = _read_env_values(self._env_path)
        config_values: dict[str, str] = {}
        for env_name, _desc, default, _validator in _CONFIG_VARS:
            resolved = default.replace("{root}", str(self._root))
            value = existing.get(env_name) or os.environ.get(env_name, "") or resolved
            config_values[env_name] = value
        changed = self._auto_resolve_internal_port_conflicts(config_values, console)
        self._env_path.write_text(
            "\n".join(f"{k}={v}" for k, v in config_values.items()) + "\n"
        )
        console.print(f"  [green]\u2705 {self.name}[/] \u2014 generated .env with defaults")
        _print_env_hint(console, self._env_path)
        if changed:
            self._reconcile_services_after_port_change(console)
        return True

    def verify(self) -> bool:
        return self._env_path.exists() and self._env_path.stat().st_size > 0

    def _auto_resolve_internal_port_conflicts(
        self,
        config_values: dict[str, str],
        console: Console,
    ) -> bool:
        internal_port_keys = [
            "RP_DISCOVERY_PORT",
            "RP_ANALYZER_PORT",
            "RP_EXTRACTOR_PORT",
            "RP_VALIDATOR_PORT",
            "RP_CODEGEN_PORT",
            "RP_ORCHESTRATOR_PORT",
            "RP_MCP_PORT",
        ]
        expected_service = {
            "RP_DISCOVERY_PORT": "discovery",
            "RP_ANALYZER_PORT": "analyzer",
            "RP_EXTRACTOR_PORT": "extractor",
            "RP_VALIDATOR_PORT": "validator",
            "RP_CODEGEN_PORT": "codegen",
            "RP_ORCHESTRATOR_PORT": "orchestrator",
            "RP_MCP_PORT": "mcp",
        }
        used_in_config: set[int] = set()
        changed: list[tuple[str, int, int]] = []
        for key in internal_port_keys:
            raw = config_values.get(key, "").strip()
            try:
                requested = int(raw)
            except (TypeError, ValueError):
                continue
            chosen = requested
            exp = expected_service.get(key, "")
            in_use = _port_in_use(chosen)
            expected_ok = _is_expected_service_on_port(chosen, exp)
            owned_by_compose = self._compose_service_owns_port(exp, chosen)
            safe_existing_listener = expected_ok and owned_by_compose
            if chosen in used_in_config or (in_use and not safe_existing_listener):
                chosen = _find_next_free_port(max(1024, requested + 1), used_in_config)
            used_in_config.add(chosen)
            if chosen != requested:
                config_values[key] = str(chosen)
                changed.append((key, requested, chosen))
        if changed:
            console.print("[yellow]Detected occupied/conflicting internal ports. Auto-remapped:[/]")
            for key, old, new in changed:
                console.print(f"[dim]- {key}: {old} -> {new}[/]")
            return True
        return False

    def _compose_service_owns_port(self, service_name: str, port: int) -> bool:
        if not service_name:
            return False
        if not any(
            (self._root / name).exists()
            for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
        ):
            return False
        docker = _docker_bin()
        if docker is None:
            return False
        try:
            result = subprocess.run(
                [docker, "compose", "port", service_name, str(port)],
                cwd=self._root,
                check=True,
                capture_output=True,
                text=True,
                env=_docker_env(),
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
        output = result.stdout.strip()
        if not output:
            return False
        return any(
            line.rsplit(":", 1)[-1].strip() == str(port)
            for line in output.splitlines()
            if ":" in line
        )

    def _reconcile_services_after_port_change(self, console: Console) -> None:
        compose_file = self._root / "docker-compose.yml"
        if not compose_file.exists():
            return
        docker = _docker_bin()
        if docker is None:
            console.print(
                "[yellow]Ports remapped in .env, but Docker not found. "
                "Services will use new ports on next start.[/]"
            )
            return
        console.print(
            "[cyan]Ports changed: reconciling Docker services with new port configuration...[/]"
        )
        try:
            subprocess.run(
                [docker, "compose", "up", "-d", "--build", "--force-recreate"],
                cwd=self._root,
                check=True,
                text=True,
                env=_docker_env(),
            )
            console.print("[green]Docker services reconciled with updated ports.[/]")
        except subprocess.CalledProcessError as exc:
            if self._retry_reconcile_after_conflict(console, docker):
                return
            console.print(
                "[yellow]Could not auto-reconcile Docker after port remap.[/]\n"
                f"[dim]{exc}[/]"
            )

    def _retry_reconcile_after_conflict(self, console: Console, docker: str) -> bool:
        for attempt in range(1, 6):
            values = _read_env_values(self._env_path)
            changed = self._auto_resolve_internal_port_conflicts(values, console)
            if not changed:
                return False
            self._env_path.write_text(
                "\n".join(f"{k}={v}" for k, v in values.items()) + "\n"
            )
            console.print(
                "[yellow]Docker reported a port bind conflict during reconcile. "
                f"Retrying with a fresh port remap (attempt {attempt}/5)...[/]"
            )
            try:
                subprocess.run(
                    [docker, "compose", "up", "-d", "--build", "--force-recreate"],
                    cwd=self._root,
                    check=True,
                    text=True,
                    env=_docker_env(),
                )
                console.print("[green]Docker services reconciled after conflict retry.[/]")
                return True
            except subprocess.CalledProcessError:
                continue
        return False


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _find_next_free_port(start: int, reserved: set[int]) -> int:
    candidate = max(1024, start)
    while candidate <= 65535:
        if candidate not in reserved and not _port_in_use(candidate):
            return candidate
        candidate += 1
    raise RuntimeError("No free TCP port available in 1024-65535")


def _is_expected_service_on_port(port: int, service_name: str) -> bool:
    if not service_name:
        return False
    if service_name == "mcp":
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/sse", timeout=1.0
            ) as resp:
                return resp.status < 500
        except Exception:
            return False
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=1.0
        ) as resp:
            if resp.status >= 500:
                return False
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return payload.get("service") == service_name
    except Exception:
        return False


def _docker_bin() -> str | None:
    docker = shutil.which("docker")
    if docker:
        return docker
    if sys.platform == "darwin":
        if Path("/usr/local/bin/docker").exists():
            return "/usr/local/bin/docker"
        if Path("/Applications/Docker.app/Contents/Resources/bin/docker").exists():
            return "/Applications/Docker.app/Contents/Resources/bin/docker"
    return None


def _docker_env() -> dict[str, str]:
    env = os.environ.copy()
    if sys.platform != "darwin":
        return env
    path_parts = env.get("PATH", "").split(":") if env.get("PATH") else []
    for candidate in (
        "/usr/local/bin",
        "/Applications/Docker.app/Contents/Resources/bin",
    ):
        if candidate not in path_parts:
            path_parts.append(candidate)
    env["PATH"] = ":".join(part for part in path_parts if part)
    return env
