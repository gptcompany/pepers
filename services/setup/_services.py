"""Step: verify external services (CAS, RAG) and optionally launch setup CLIs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import questionary
import requests
from rich.console import Console

_EXTERNAL_SERVICES = [
    {
        "name": "CAS Service",
        "env_urls": ["RP_VALIDATOR_CAS_URL", "RP_CAS_URL"],
        "default_url": "http://localhost:8769",
        "health_path": "/health",
        "setup_cmd": "cas-setup",
        "description": "CAS validation (SymPy, SageMath, MATLAB, WolframAlpha)",
        "local_repo": "cas-service",
        "local_module": "cas_service.setup.main",
        "systemd_units": ["cas-service.service", "cas.service"],
        "setup_hint": (
            "Install & run CAS Service:\n"
            "  cd /path/to/cas-service && cas-setup\n"
            "  Or: uv run python -m cas_service.main"
        ),
    },
    {
        "name": "RAG Service",
        "env_urls": ["RP_EXTRACTOR_RAG_URL", "RP_RAG_QUERY_URL", "RP_RAG_URL"],
        "default_url": "http://localhost:8767",
        "health_path": "/health",
        "setup_cmd": "rag-setup",
        "description": "PDF extraction + knowledge graph via RAGAnything",
        "local_repo": "rag-service",
        "local_module": "scripts.setup",
        "local_module_needs_pythonpath": True,
        "systemd_units": ["raganything.service", "rag-service.service"],
        "setup_hint": (
            "Install & run RAG Service:\n"
            "  cd /path/to/rag-service && rag-setup\n"
            "  Or: ./scripts/raganything_start.sh"
        ),
    },
]


class ExternalServiceCheck:
    """Check a single external service."""

    def __init__(self, svc: dict) -> None:
        self._svc = svc
        self.name = svc["name"]
        self.description = svc.get("description", "")

    def _url(self) -> str:
        env_urls = self._svc.get("env_urls")
        if isinstance(env_urls, list):
            for key in env_urls:
                val = os.environ.get(key, "").strip()
                if val:
                    return val
        env_url = self._svc.get("env_url")
        if isinstance(env_url, str):
            val = os.environ.get(env_url, "").strip()
            if val:
                return val
        return self._svc["default_url"]

    def _port(self) -> int | None:
        parsed = urlparse(self._url())
        return parsed.port

    def _local_setup_fallback(self) -> tuple[list[str], Path, dict[str, str], str] | None:
        """Return local repo fallback command when CLI is not installed in PATH."""
        repo_name = self._svc.get("local_repo")
        module_name = self._svc.get("local_module")
        if not isinstance(repo_name, str) or not isinstance(module_name, str):
            return None

        # Prefer a sibling repo next to pepers, but fall back to CWD parent when run elsewhere.
        pepers_root = Path(__file__).resolve().parents[2]
        candidate_roots = [
            pepers_root.parent / repo_name,
            Path.cwd().resolve().parent / repo_name,
        ]
        repo_dir = next((p for p in candidate_roots if p.exists()), None)
        if repo_dir is None:
            return None

        venv_python = repo_dir / ".venv" / "bin" / "python"
        if not venv_python.exists():
            return None

        env = {"PYTHONHASHSEED": "0"}
        if self._svc.get("local_module_needs_pythonpath"):
            env["PYTHONPATH"] = str(repo_dir)

        cmd = [str(venv_python), "-m", module_name]
        display = f"{venv_python} -m {module_name}"
        return cmd, repo_dir, env, display

    def _systemd_boot_enabled(self) -> str | None:
        units = self._svc.get("systemd_units")
        if not isinstance(units, list):
            return None

        for unit in units:
            if not isinstance(unit, str):
                continue
            for cmd in (
                ["systemctl", "is-enabled", unit],
                ["systemctl", "--user", "is-enabled", unit],
            ):
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                    )
                except FileNotFoundError:
                    return None
                status = result.stdout.strip().lower()
                if result.returncode == 0 and status.startswith("enabled"):
                    return unit
        return None

    def _docker_boot_enabled(self) -> str | None:
        port = self._port()
        if port is None or shutil.which("docker") is None:
            return None

        try:
            ps_result = subprocess.run(
                ["docker", "ps", "--format", "{{.ID}}"],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return None
        if ps_result.returncode != 0:
            return None

        ids = [line.strip() for line in ps_result.stdout.splitlines() if line.strip()]
        for cid in ids:
            inspect = subprocess.run(
                [
                    "docker",
                    "inspect",
                    cid,
                    "--format",
                    "{{.Name}}|{{.HostConfig.RestartPolicy.Name}}|"
                    "{{json .NetworkSettings.Ports}}",
                ],
                capture_output=True,
                text=True,
            )
            if inspect.returncode != 0:
                continue
            raw = inspect.stdout.strip()
            parts = raw.split("|", 2)
            if len(parts) != 3:
                continue

            container_name, restart_policy, ports_json = parts
            if restart_policy in {"", "no"}:
                continue
            try:
                ports = json.loads(ports_json)
            except json.JSONDecodeError:
                continue

            bindings = ports.get(f"{port}/tcp")
            if isinstance(bindings, list) and any(
                isinstance(item, dict) and item.get("HostPort") == str(port)
                for item in bindings
            ):
                return container_name.lstrip("/")
        return None

    def _crontab_boot_enabled(self) -> bool:
        port = self._port()
        if port is None:
            return False
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return False
        if result.returncode != 0:
            return False

        needle = f":{port}"
        name_hint = self.name.split()[0].lower()
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "@reboot" in line and (needle in line or name_hint in line.lower()):
                return True
        return False

    def check_boot_persistence(self) -> tuple[bool, str]:
        """Best-effort check for reboot persistence (systemd/docker/crontab)."""
        unit = self._systemd_boot_enabled()
        if unit:
            return True, f"systemd:{unit}"

        container = self._docker_boot_enabled()
        if container:
            return True, f"docker:{container}"

        if self._crontab_boot_enabled():
            return True, "crontab:@reboot"

        return False, "missing"

    def check(self) -> bool:
        url = self._url().rstrip("/") + self._svc["health_path"]
        try:
            resp = requests.get(url, timeout=5)
            return resp.status_code < 500
        except (requests.ConnectionError, requests.Timeout):
            return False

    def install(self, console: Console) -> bool:
        console.print(f"[yellow]{self.name} is not reachable at {self._url()}[/]")
        setup_cmd = self._svc.get("setup_cmd")
        if isinstance(setup_cmd, str) and shutil.which(setup_cmd):
            if questionary.confirm(
                f"Launch {setup_cmd} now?",
                default=True,
            ).ask():
                try:
                    result = subprocess.run([setup_cmd], check=False)
                except OSError as exc:
                    console.print(f"[red]Failed to launch {setup_cmd}:[/] {exc}")
                else:
                    if result.returncode == 0:
                        return True
                    console.print(
                        f"[red]{setup_cmd} failed (exit {result.returncode})[/]"
                    )
        else:
            fallback = self._local_setup_fallback()
            if fallback is not None:
                cmd, cwd, env_extra, display = fallback
                if questionary.confirm(
                    f"Launch local setup wizard from {cwd.name}? ({display})",
                    default=True,
                ).ask():
                    run_env = os.environ.copy()
                    # Preserve existing PYTHONPATH if present.
                    if "PYTHONPATH" in env_extra and run_env.get("PYTHONPATH"):
                        env_extra = env_extra.copy()
                        env_extra["PYTHONPATH"] = (
                            f"{env_extra['PYTHONPATH']}:{run_env['PYTHONPATH']}"
                        )
                    run_env.update(env_extra)
                    try:
                        result = subprocess.run(cmd, cwd=cwd, env=run_env, check=False)
                    except OSError as exc:
                        console.print(f"[red]Failed to launch local setup:[/] {exc}")
                    else:
                        if result.returncode == 0:
                            return True
                        console.print(
                            f"[red]Local setup failed (exit {result.returncode})[/]"
                        )
        console.print(f"[dim]{self._svc['setup_hint']}[/]")
        return False  # can't auto-install external services

    def verify(self) -> bool:
        return self.check()


class ExternalServicePersistenceCheck:
    """Ensure a reachable external service survives reboot."""

    def __init__(self, svc: dict) -> None:
        self._svc = svc
        self._health = ExternalServiceCheck(svc)
        self.name = f"{svc['name']} boot persistence"
        self.description = "Reboot survival via systemd/docker/@reboot"

    def check(self) -> bool:
        # If service is currently down, skip persistence gating here.
        # Reachability is handled by ExternalServiceCheck.
        if not self._health.check():
            return True
        ok, _ = self._health.check_boot_persistence()
        return ok

    def install(self, console: Console) -> bool:
        if not self._health.check():
            console.print(
                f"[dim]Skipping {self.name}: service is currently unreachable.[/]"
            )
            return True

        ok, detail = self._health.check_boot_persistence()
        if ok:
            console.print(f"[green]{self._svc['name']} persistence detected:[/] {detail}")
            return True

        console.print(
            f"[yellow]{self._svc['name']} is reachable but not boot-persistent.[/]"
        )
        units = self._svc.get("systemd_units")
        if isinstance(units, list) and units:
            console.print("[dim]Recommended (systemd):[/]")
            for unit in units:
                if isinstance(unit, str):
                    console.print(f"  sudo systemctl enable --now {unit}")
        console.print("[dim]Alternative:[/] run in Docker with restart policy enabled.")
        return False

    def verify(self) -> bool:
        return self.check()


def get_all_steps() -> list:
    steps: list = []
    for svc in _EXTERNAL_SERVICES:
        steps.append(ExternalServiceCheck(svc))
        steps.append(ExternalServicePersistenceCheck(svc))
    return steps
