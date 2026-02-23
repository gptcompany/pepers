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

        all_ok = True

        # Internal PePeRS services
        for svc_name, port in SERVICE_PORTS.items():
            env_key = f"RP_{svc_name.upper()}_PORT"
            actual_port = int(os.environ.get(env_key, str(port)))
            url = f"http://localhost:{actual_port}/health"
            ok = _check_http(url)
            status = "[green]✅ OK[/]" if ok else "[red]❌ Down[/]"
            table.add_row(svc_name.capitalize(), url, status)
            if not ok:
                all_ok = False

        # External services
        for name, (env_key, default_url, path) in _EXTERNAL.items():
            base = os.environ.get(env_key, default_url)
            url = base.rstrip("/") + path
            ok = _check_http(url)
            status = "[green]✅ OK[/]" if ok else "[red]❌ Down[/]"
            table.add_row(name, url, status)
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
