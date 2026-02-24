"""Step: aggregated health check for all PePeRS services + externals."""

from __future__ import annotations

import os

import requests
from rich.console import Console
from rich.table import Table

from shared.config import SERVICE_PORTS

_EXTERNAL = {
    "CAS Service": ("RP_CAS_URL", "http://localhost:8769", "/health"),
    "RAG Service": ("RP_RAG_URL", "http://localhost:8767", "/health"),
    "Ollama": ("RP_OLLAMA_URL", "http://localhost:11434", "/"),
}


def _check_http(url: str, timeout: float = 3.0) -> bool:
    try:
        resp = requests.get(url, timeout=timeout)
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

    def check(self) -> bool:
        # Always run the full check in install()
        return False

    def install(self, console: Console) -> bool:
        table = Table(title="Service Health", show_lines=False)
        table.add_column("Service", style="bold")
        table.add_column("URL")
        table.add_column("Status")
        table.add_column("Details", style="dim")

        all_ok = True

        # Internal PePeRS services
        for svc_name, port in SERVICE_PORTS.items():
            env_key = f"RP_{svc_name.upper()}_PORT"
            actual_port = int(os.environ.get(env_key, str(port)))
            url = f"http://localhost:{actual_port}/health"
            ok = _check_http(url)
            status = "[green]✅ OK[/]" if ok else "[red]❌ Down[/]"
            table.add_row(svc_name.capitalize(), url, status, f":{actual_port}")
            if not ok:
                all_ok = False

        # External services with capability discovery
        for name, (env_key, default_url, path) in _EXTERNAL.items():
            base = os.environ.get(env_key, default_url)
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

        if not all_ok:
            console.print(
                "\n[yellow]Some services are not reachable. "
                "Start them before using PePeRS.[/]"
            )
        else:
            console.print("\n[green]All services are healthy![/]")

        return True  # always "succeeds" — it's informational

    def verify(self) -> bool:
        return True
