"""Step: aggregated health check for all PePeRS services + externals."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import requests
from rich.console import Console
from rich.table import Table

from shared.config import SERVICE_PORTS

_INTERNAL_HEALTH_PATHS = {
    "mcp": "/sse",
}

_EXTERNAL = {
    "CAS Service": (("RP_VALIDATOR_CAS_URL", "RP_CAS_URL"), "http://localhost:8769", "/health"),
    "RAG Service": (
        ("RP_EXTRACTOR_RAG_URL", "RP_RAG_QUERY_URL", "RP_RAG_URL"),
        "http://localhost:8767",
        "/health",
    ),
    "Ollama": (("RP_CODEGEN_OLLAMA_URL", "RP_OLLAMA_URL"), "http://localhost:11434", "/"),
}


def _env_first(keys: tuple[str, ...], default: str) -> str:
    env_file_values = _read_env_file()
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
        file_value = env_file_values.get(key, "").strip()
        if file_value:
            return file_value
    return default


def _read_env_file() -> dict[str, str]:
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    except OSError:
        return {}
    return values


def _check_http(url: str, timeout: float = 3.0) -> bool:
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
        return resp.status_code < 500
    except (requests.ConnectionError, requests.Timeout):
        return False


def _discover_cas_details(base_url: str) -> str:
    """Query CAS /engines to get engine names and count."""
    try:
        resp = requests.get(f"{base_url}/engines", timeout=5)
        data = resp.json()
        engines = data.get("engines", [])
        names = [e.get("name", "?") for e in engines]
        return f"{', '.join(names)} ({len(names)} eng.)"
    except Exception:
        return ""


def _discover_rag_details(base_url: str) -> str:
    """Query RAG /status to get queue and circuit breaker info."""
    try:
        resp = requests.get(f"{base_url}/status", timeout=5)
        data = resp.json()
        cb = data.get("circuit_breaker", {}).get("state", "?")
        queue = data.get("queue", {})
        active = queue.get("active", "?")
        max_q = queue.get("max", "?")
        return f"queue: {active}/{max_q}, CB: {cb}"
    except Exception:
        return ""


class AggregatedHealthCheck:
    name = "Aggregated health check"
    description = "Verify PePeRS, CAS, RAG, and Ollama endpoints"
    auto_reconcile_when_configured = True

    def __init__(self) -> None:
        self._last_all_ok = False
        self._has_run = False

    def check(self) -> bool:
        # Pending until executed at least once in current guided session.
        return self._has_run

    def install(self, console: Console) -> bool:
        table = Table(title="Service Health", show_lines=False)
        table.add_column("Service", style="bold")
        table.add_column("URL")
        table.add_column("Status")
        table.add_column("Details", style="dim")

        all_ok = True

        # Internal PePeRS services
        env_file_values = _read_env_file()
        for svc_name, port in SERVICE_PORTS.items():
            env_key = f"RP_{svc_name.upper()}_PORT"
            raw_port = (
                os.environ.get(env_key)
                or env_file_values.get(env_key)
                or str(port)
            )
            try:
                actual_port = int(raw_port)
            except (TypeError, ValueError):
                actual_port = port
            health_path = _INTERNAL_HEALTH_PATHS.get(svc_name, "/health")
            url = f"http://localhost:{actual_port}{health_path}"
            ok = _check_http(url)
            status = "[green]✅ OK[/]" if ok else "[red]❌ Down[/]"
            table.add_row(svc_name.capitalize(), url, status, f":{actual_port}")
            if not ok:
                all_ok = False

        # External services with capability discovery
        for name, (env_keys, default_url, path) in _EXTERNAL.items():
            base = _env_first(env_keys, default_url)
            url = base.rstrip("/") + path
            ok = _check_http(url)
            status = "[green]✅ OK[/]" if ok else "[red]❌ Down[/]"

            details = ""
            if ok:
                if name == "CAS Service":
                    details = _discover_cas_details(base.rstrip("/"))
                elif name == "RAG Service":
                    details = _discover_rag_details(base.rstrip("/"))

            table.add_row(name, url, status, details)
            if not ok:
                all_ok = False

        console.print(table)

        self._last_all_ok = all_ok
        self._has_run = True
        if not all_ok:
            console.print(
                "\n[yellow]Some services are not reachable. "
                "Start them before using PePeRS.[/]"
            )
        else:
            console.print("\n[green]All services are healthy![/]")

        return True

    def verify(self) -> bool:
        return self._last_all_ok


# ── Easy-mode verdict ────────────────────────────────────────


class Readiness(Enum):
    READY = "ready"
    READY_WITH_LIMITATIONS = "ready_with_limitations"
    NOT_READY = "not_ready"


@dataclass
class SetupVerdict:
    readiness: Readiness
    core_ok: list[str] = field(default_factory=list)
    core_failed: list[str] = field(default_factory=list)
    external_ok: list[str] = field(default_factory=list)
    external_down: list[str] = field(default_factory=list)
    optional_skipped: list[str] = field(default_factory=list)


# Tier classification for step names
TIER_CORE = "core"
TIER_EXTERNAL = "external"
TIER_OPTIONAL = "optional"


def compute_verdict(
    results: list[tuple[str, str]],
    tier_map: dict[str, str],
) -> SetupVerdict:
    """Classify results by tier and compute overall readiness."""
    core_ok: list[str] = []
    core_failed: list[str] = []
    external_ok: list[str] = []
    external_down: list[str] = []
    optional_skipped: list[str] = []

    for name, status in results:
        tier = tier_map.get(name, TIER_OPTIONAL)
        if tier == TIER_CORE:
            if status == "ok":
                core_ok.append(name)
            else:
                core_failed.append(name)
        elif tier == TIER_EXTERNAL:
            if status == "ok":
                external_ok.append(name)
            else:
                external_down.append(name)
        else:
            optional_skipped.append(name)

    if core_failed:
        readiness = Readiness.NOT_READY
    elif external_down:
        readiness = Readiness.READY_WITH_LIMITATIONS
    else:
        readiness = Readiness.READY

    return SetupVerdict(
        readiness=readiness,
        core_ok=core_ok,
        core_failed=core_failed,
        external_ok=external_ok,
        external_down=external_down,
        optional_skipped=optional_skipped,
    )


def print_verdict(verdict: SetupVerdict, console: Console) -> None:
    """Print a coloured readiness banner with actionable details."""
    banners = {
        Readiness.READY: ("green", "\u2705  READY"),
        Readiness.READY_WITH_LIMITATIONS: ("yellow", "\u26a0\ufe0f  READY WITH LIMITATIONS"),
        Readiness.NOT_READY: ("red", "\u274c  NOT READY"),
    }
    colour, label = banners[verdict.readiness]

    console.print()
    console.print(f"[bold {colour}]\u2554{'═' * 50}\u2557[/]")
    console.print(f"[bold {colour}]\u2551{label:^50}\u2551[/]")
    console.print(f"[bold {colour}]\u255a{'═' * 50}\u255d[/]")

    if verdict.core_failed:
        console.print("\n[red]Core requirements missing:[/]")
        for name in verdict.core_failed:
            console.print(f"  \u2022 {name}")

    if verdict.external_down:
        console.print("\n[yellow]External services unavailable:[/]")
        for name in verdict.external_down:
            console.print(f"  \u2022 {name}")

    if verdict.optional_skipped:
        console.print(
            "\n[dim]Optional tools not configured:[/]\n"
            "  \u2022 Run [bold]pepers-setup guided[/] for full configuration"
        )
