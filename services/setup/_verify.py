"""Step: aggregated health check for all PePeRS services + externals."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

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

_EXTERNAL_RUNTIME_KEYS = {
    "CAS Service": "cas",
    "RAG Service": "rag",
    "Ollama": "ollama",
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


def _check_http(
    url: str,
    timeout: float = 3.0,
    *,
    expected_service: str | None = None,
) -> bool:
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
        if resp.status_code >= 500:
            return False
        if expected_service is None:
            return True
        try:
            data = resp.json()
        except ValueError:
            return False
        service = str(data.get("service", "")).lower()
        status = str(data.get("status", "")).lower()
        if expected_service == "rag":
            return ("rag" in service or "rag_initialized" in data) and status == "ok"
        if expected_service == "cas":
            return "cas" in service and status == "ok"
        return expected_service == service and status == "ok"
    except (requests.ConnectionError, requests.Timeout):
        return False


def _orchestrator_runtime_health() -> dict | None:
    """Return orchestrator /status/services when reachable.

    This reflects the container-side view of internal/external dependencies and
    is more authoritative than host-only localhost probes when PePeRS runs in
    Docker and host ports may be forwarded or proxied.
    """
    env_file_values = _read_env_file()
    raw_port = (
        os.environ.get("RP_ORCHESTRATOR_PORT")
        or env_file_values.get("RP_ORCHESTRATOR_PORT")
        or str(SERVICE_PORTS["orchestrator"])
    )
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = SERVICE_PORTS["orchestrator"]
    url = f"http://localhost:{port}/status/services"
    try:
        resp = requests.get(url, timeout=4)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    return data if isinstance(data, dict) else None


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

    def _collect_rows(self) -> tuple[list[tuple[str, str, bool, str]], bool, bool]:
        rows: list[tuple[str, str, bool, str]] = []
        all_ok = True
        internal_ok = True
        env_file_values = _read_env_file()
        runtime_health = _orchestrator_runtime_health()

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
            expected = None if svc_name == "mcp" else svc_name
            ok = _check_http(url, expected_service=expected)
            rows.append(
                (
                    svc_name.capitalize(),
                    url,
                    ok,
                    f":{actual_port}",
                )
            )
            if not ok:
                all_ok = False
                internal_ok = False

        for name, (env_keys, default_url, path) in _EXTERNAL.items():
            base = _env_first(env_keys, default_url)
            host_url = base.rstrip("/") + path
            expected = None
            if name == "CAS Service":
                expected = "cas"
            elif name == "RAG Service":
                expected = "rag"

            host_ok = _check_http(host_url, expected_service=expected)
            ok = host_ok
            display_url = host_url
            detail_parts: list[str] = []

            runtime_dep = None
            if runtime_health:
                runtime_dep = (
                    (runtime_health.get("external") or {}).get("deps") or {}
                ).get(_EXTERNAL_RUNTIME_KEYS[name])
            if isinstance(runtime_dep, dict):
                runtime_base = str(runtime_dep.get("url") or base).rstrip("/")
                display_url = runtime_base + path
                runtime_ok = bool(runtime_dep.get("healthy"))
                ok = runtime_ok
                if host_ok and not runtime_ok:
                    detail_parts.append("host OK, orchestrator cannot reach it")
                elif runtime_ok and not host_ok:
                    detail_parts.append("orchestrator OK, host probe failed")

            details = ""
            if ok:
                extra = ""
                if host_ok:
                    if name == "CAS Service":
                        extra = _discover_cas_details(base.rstrip("/"))
                    elif name == "RAG Service":
                        extra = _discover_rag_details(base.rstrip("/"))
                if extra:
                    detail_parts.append(extra)
            details = "; ".join(part for part in detail_parts if part)
            rows.append((name, display_url, ok, details))
            if not ok:
                all_ok = False

        return rows, all_ok, internal_ok

    def _print_rows(
        self,
        console: Console,
        rows: list[tuple[str, str, bool, str]],
    ) -> None:
        table = Table(title="Service Health", show_lines=False)
        table.add_column("Service", style="bold")
        table.add_column("URL")
        table.add_column("Status")
        table.add_column("Details", style="dim")
        for name, url, ok, details in rows:
            status = "[green]✅ OK[/]" if ok else "[red]❌ Down[/]"
            table.add_row(name, url, status, details)
        console.print(table)

    def install(self, console: Console) -> bool:
        ports_changed = self._maybe_auto_remap_internal_ports(console)
        if ports_changed:
            console.print(
                "[cyan]Waiting for remapped PePeRS services to settle before re-checking...[/]"
            )
            rows, all_ok, internal_ok = self._wait_for_internal_services()
        else:
            rows, all_ok, internal_ok = self._collect_rows()
        if not internal_ok and self._maybe_auto_reconcile_internal_services(console):
            console.print(
                "[cyan]Waiting for Docker-reconciled PePeRS services to settle...[/]"
            )
            rows, all_ok, internal_ok = self._wait_for_internal_services()
            console.print(
                "[cyan]Re-checking PePeRS service health after Docker reconcile...[/]"
            )
        if self._ollama_down(rows) and self._maybe_auto_remediate_ollama(console):
            console.print(
                "[cyan]Re-checking Ollama after automatic remediation...[/]"
            )
            rows, all_ok, internal_ok = self._collect_rows()

        self._print_rows(console, rows)

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
        # Live verification to avoid stale "OK" after services go down.
        _rows, all_ok, _internal_ok = self._collect_rows()
        self._last_all_ok = all_ok
        return all_ok

    def verify_internal(self) -> bool:
        _rows, _all_ok, internal_ok = self._collect_rows()
        return internal_ok

    def _maybe_auto_remap_internal_ports(self, console: Console) -> bool:
        try:
            from services.setup._config import EnvConfig, _read_env_values
        except Exception:
            return False
        root = Path.cwd()
        env_path = root / ".env"
        if not env_path.exists():
            return False
        values = _read_env_values(env_path)
        for svc_name, port in SERVICE_PORTS.items():
            env_key = f"RP_{svc_name.upper()}_PORT"
            values.setdefault(env_key, str(port))
        step = EnvConfig(root)
        changed = step._auto_resolve_internal_port_conflicts(values, console)
        if not changed:
            return False
        env_path.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n")
        console.print(
            "[cyan]Updated .env with remapped internal ports before health verification.[/]"
        )
        step._reconcile_services_after_port_change(console)
        return True

    def _wait_for_internal_services(
        self,
        timeout_s: float = 12.0,
        interval_s: float = 1.0,
    ) -> tuple[list[tuple[str, str, bool, str]], bool, bool]:
        deadline = time.time() + timeout_s
        latest = self._collect_rows()
        while time.time() < deadline:
            latest = self._collect_rows()
            _rows, _all_ok, internal_ok = latest
            if internal_ok:
                break
            time.sleep(interval_s)
        return latest

    def _maybe_auto_reconcile_internal_services(self, console: Console) -> bool:
        try:
            from services.setup._docker import DockerComposeUp
        except Exception:
            return False
        step = DockerComposeUp(Path.cwd())
        if step._compose_file() is None:
            return False
        console.print(
            "[yellow]Some internal PePeRS services are down. "
            "Attempting automatic Docker reconcile...[/]"
        )
        return step.install(console)

    def _ollama_down(self, rows: list[tuple[str, str, bool, str]]) -> bool:
        for name, _url, ok, _details in rows:
            if name == "Ollama":
                return not ok
        return False

    def _maybe_auto_remediate_ollama(self, console: Console) -> bool:
        env_keys, default_url, path = _EXTERNAL["Ollama"]
        base = _env_first(env_keys, default_url).rstrip("/")
        parsed = urlparse(base)
        host = (parsed.hostname or "").strip().lower()
        if host not in {"localhost", "127.0.0.1"}:
            console.print(
                "[yellow]Configured Ollama endpoint is external. "
                "Automatic local start skipped.[/]"
            )
            return False

        try:
            from services.setup._cli_tools import OllamaCheck
        except Exception:
            return False

        step = OllamaCheck()
        if not step.check():
            console.print(
                "[yellow]Ollama is not installed. Attempting automatic installation...[/]"
            )
            if not step.install(console):
                return False

        url = base + path
        if _check_http(url):
            return True

        console.print(
            "[yellow]Ollama is installed but not serving. "
            "Attempting automatic start...[/]"
        )
        if not self._start_local_ollama():
            return False
        return self._wait_for_endpoint(url)

    def _start_local_ollama(self) -> bool:
        ollama_bin = shutil.which("ollama")
        if not ollama_bin:
            return False
        try:
            subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError:
            return False

    def _wait_for_endpoint(
        self,
        url: str,
        timeout_s: float = 12.0,
        interval_s: float = 1.0,
    ) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if _check_http(url):
                return True
            time.sleep(interval_s)
        return False


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
