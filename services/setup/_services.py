"""Step: verify external services (CAS, RAG) and optionally launch setup CLIs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
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
        "guided_install": True,
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
        "guided_install": True,
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


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _ask_select_safe(prompt: str, choices: list[str], default: str) -> str:
    try:
        answer = questionary.select(
            prompt,
            choices=choices,
            default=default,
        ).ask()
    except EOFError:
        return default
    return answer or default


def _ask_confirm_safe(prompt: str, default: bool = True) -> bool:
    try:
        answer = questionary.confirm(prompt, default=default).ask()
    except EOFError:
        return default
    if answer is None:
        return default
    return bool(answer)


def _ask_text_safe(prompt: str, default: str = "") -> str:
    try:
        answer = questionary.text(prompt, default=default).ask()
    except EOFError:
        return default
    return (answer or default).strip()


class ExternalServiceCheck:
    """Check a single external service."""
    auto_reconcile_when_configured = True

    def __init__(self, svc: dict, project_root: Path | None = None) -> None:
        self._svc = svc
        self._project_root = project_root
        self.name = svc["name"]
        self.description = svc.get("description", "")
        self._active_url: str | None = None

    def _env_path(self) -> Path | None:
        if self._project_root is None:
            return None
        return self._project_root / ".env"

    def _read_env_file(self) -> dict[str, str]:
        env_path = self._env_path()
        if env_path is None or not env_path.exists():
            return {}
        values: dict[str, str] = {}
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    def _persist_url(self, url: str, console: Console) -> None:
        env_urls = self._svc.get("env_urls")
        if not isinstance(env_urls, list) or not env_urls:
            return
        keys = [k for k in env_urls if isinstance(k, str)]
        if not keys:
            return
        env_path = self._env_path()
        if env_path is None:
            return
        values = self._read_env_file()
        for key in keys:
            values[key] = url
        lines = [f"{k}={v}" for k, v in values.items()]
        env_path.write_text("\n".join(lines) + "\n")
        for key in keys:
            os.environ[key] = url
        console.print(f"[green]Saved {', '.join(keys)}={url} in {env_path}[/]")

    def _persist_url_silent(self, url: str) -> None:
        env_urls = self._svc.get("env_urls")
        if not isinstance(env_urls, list) or not env_urls:
            return
        keys = [k for k in env_urls if isinstance(k, str)]
        if not keys:
            return
        env_path = self._env_path()
        if env_path is None:
            return
        values = self._read_env_file()
        for key in keys:
            values[key] = url
        env_path.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n")
        for key in keys:
            os.environ[key] = url

    def _set_runtime_url(self, url: str) -> None:
        env_urls = self._svc.get("env_urls")
        if not isinstance(env_urls, list) or not env_urls:
            return
        for key in env_urls:
            if isinstance(key, str):
                os.environ[key] = url

    def _url(self) -> str:
        if self._active_url:
            return self._active_url

        env_urls = self._svc.get("env_urls")
        env_file_values = self._read_env_file()
        if isinstance(env_urls, list):
            for key in env_urls:
                val = os.environ.get(key, "").strip()
                if val:
                    return val
                file_val = env_file_values.get(key, "").strip()
                if file_val:
                    return file_val
        env_url = self._svc.get("env_url")
        if isinstance(env_url, str):
            val = os.environ.get(env_url, "").strip()
            if val:
                return val
        return self._svc["default_url"]

    def _port(self) -> int | None:
        parsed = urlparse(self._url())
        return parsed.port

    def _normalize_user_url(self, raw: str) -> str:
        value = raw.strip()
        if value.isdigit():
            return f"http://localhost:{value}"
        if value.startswith(("http://", "https://")):
            return value.rstrip("/")
        return f"http://{value}".rstrip("/")

    def _runtime_env_overrides(self) -> dict[str, str]:
        """Propagate selected custom endpoint into child setup processes."""
        url = self._active_url or self._url()
        parsed = urlparse(url)
        port = parsed.port
        host = parsed.hostname or "localhost"
        overrides: dict[str, str] = {}
        if self.name == "CAS Service" and port is not None:
            overrides["CAS_PORT"] = str(port)
        if self.name == "RAG Service" and port is not None:
            overrides["RAG_PORT"] = str(port)
            overrides["RAG_HOST"] = host
        return overrides

    def _probe_url(self, base_url: str, timeout: int = 3, *, strict_identity: bool = True) -> bool:
        health = base_url.rstrip("/") + self._svc["health_path"]
        try:
            resp = requests.get(health, timeout=timeout)
            if resp.status_code >= 500:
                return False
            if not strict_identity:
                return True
            # Tighten discovery to avoid false positives from unrelated /health endpoints.
            if self.name == "CAS Service":
                try:
                    data = resp.json()
                except ValueError:
                    return False
                service = str(data.get("service", "")).lower()
                return "cas" in service and data.get("status") == "ok"
            if self.name == "RAG Service":
                try:
                    data = resp.json()
                except ValueError:
                    return False
                service = str(data.get("service", "")).lower()
                return ("rag" in service or "rag_initialized" in data) and data.get("status") == "ok"
            return True
        except (requests.ConnectionError, requests.Timeout):
            return False

    def _runtime_dep_health(self) -> dict | None:
        """Return orchestrator-side health for this external dependency.

        When PePeRS runs in Docker on macOS, host localhost probes can hit a
        forwarded or proxied listener that containers cannot reach. Prefer the
        orchestrator view when available.
        """
        dep_key = None
        if self.name == "CAS Service":
            dep_key = "cas"
        elif self.name == "RAG Service":
            dep_key = "rag"
        if dep_key is None:
            return None

        try:
            from services.setup._verify import _orchestrator_runtime_health
        except Exception:
            return None

        runtime = _orchestrator_runtime_health()
        if not runtime:
            return None
        deps = (runtime.get("external") or {}).get("deps") or {}
        dep = deps.get(dep_key)
        return dep if isinstance(dep, dict) else None

    def _runtime_url_matches_local_target(self, base_url: str, runtime_url: str) -> bool:
        base = urlparse(base_url.rstrip("/"))
        runtime = urlparse(runtime_url.rstrip("/"))

        if (base.scheme or "http") != (runtime.scheme or "http"):
            return False
        if base.port != runtime.port:
            return False

        base_host = (base.hostname or "").strip().lower()
        runtime_host = (runtime.hostname or "").strip().lower()
        if base_host == runtime_host:
            return True

        localhost_aliases = {"localhost", "127.0.0.1"}
        gateway_aliases = {"host.docker.internal", "gateway.docker.internal"}
        return base_host in localhost_aliases and runtime_host in gateway_aliases

    def _runtime_dep_needs_sync(self, base_url: str) -> bool:
        runtime_dep = self._runtime_dep_health()
        if not runtime_dep:
            return False
        runtime_url = str(runtime_dep.get("url") or "").rstrip("/")
        if not runtime_url:
            return False
        return not self._runtime_url_matches_local_target(base_url, runtime_url)

    def _probe_effective(
        self,
        base_url: str,
        timeout: int = 3,
        *,
        strict_identity: bool = True,
    ) -> bool:
        host_ok = self._probe_url(
            base_url,
            timeout=timeout,
            strict_identity=strict_identity,
        )
        runtime_dep = self._runtime_dep_health()
        if not runtime_dep:
            return host_ok

        runtime_url = str(runtime_dep.get("url") or "").rstrip("/")
        if runtime_url and self._runtime_url_matches_local_target(base_url, runtime_url):
            return bool(runtime_dep.get("healthy"))
        return host_ok

    def _host_only_warning(self, base_url: str) -> str | None:
        runtime_dep = self._runtime_dep_health()
        if not runtime_dep:
            return None
        runtime_url = str(runtime_dep.get("url") or "").rstrip("/")
        if not runtime_url:
            return None
        if not self._runtime_url_matches_local_target(base_url, runtime_url):
            return None
        host_ok = self._probe_url(base_url, strict_identity=True)
        runtime_ok = bool(runtime_dep.get("healthy"))
        if host_ok and not runtime_ok:
            return (
                f"{self.name} responds on the host at {base_url}, "
                f"but the PePeRS containers cannot reach {runtime_url}. "
                "A local proxy/tunnel may be occupying this port."
            )
        return None

    def _suggest_clean_local_url(self, base_url: str) -> str | None:
        parsed = urlparse(base_url.rstrip("/"))
        host = (parsed.hostname or "").strip().lower()
        port = parsed.port
        if host not in {"localhost", "127.0.0.1"} or port is None:
            return None

        try:
            from services.setup._config import _find_next_free_port, _port_in_use
        except Exception:
            return None

        default_port = urlparse(self._svc["default_url"]).port
        reserved: set[int] = set()

        def candidate_url(candidate_port: int) -> str:
            scheme = parsed.scheme or "http"
            return f"{scheme}://localhost:{candidate_port}"

        for candidate in (default_port, port + 1):
            if candidate is None or candidate <= 0:
                continue
            reserved.add(candidate)
            url = candidate_url(candidate)
            if self._probe_effective(url, strict_identity=True):
                return url
            if not _port_in_use(candidate):
                return url

        start = max(1024, (default_port or port) + 1, port + 1)
        try:
            clean_port = _find_next_free_port(start, reserved)
        except RuntimeError:
            return None
        return candidate_url(clean_port)

    def _auto_rehome_host_only_url(
        self,
        console: Console,
        *,
        preferred_url: str | None = None,
    ) -> bool:
        base_url = preferred_url or self._active_url or self._url()
        warning = self._host_only_warning(base_url)
        if not warning:
            return False

        clean_url = self._suggest_clean_local_url(base_url)
        if not clean_url or clean_url.rstrip("/") == base_url.rstrip("/"):
            return False

        console.print(f"[yellow]{warning}[/]")
        console.print(
            f"[cyan]Switching {self.name} to a clean local target: {clean_url}[/]"
        )
        self._active_url = clean_url
        self._persist_url(clean_url, console)
        return True

    def _discovery_candidates(self) -> list[str]:
        candidates: list[str] = []

        def add(url: str) -> None:
            value = url.strip().rstrip("/")
            if value and value not in candidates:
                candidates.append(value)

        add(self._svc["default_url"])
        env_urls = self._svc.get("env_urls")
        env_values = self._read_env_file()
        if isinstance(env_urls, list):
            for key in env_urls:
                if not isinstance(key, str):
                    continue
                add(os.environ.get(key, ""))
                add(env_values.get(key, ""))

        default_port = urlparse(self._svc["default_url"]).port
        if default_port is not None:
            for port in (default_port - 2, default_port - 1, default_port, default_port + 1, default_port + 2):
                if port > 0:
                    add(f"http://localhost:{port}")

        if shutil.which("docker") is not None:
            try:
                result = subprocess.run(
                    ["docker", "ps", "--format", "{{.Ports}}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError:
                result = None
            if result and result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.replace(",", " ").split()
                    for part in parts:
                        if "->" not in part:
                            continue
                        host_side = part.split("->", 1)[0]
                        if ":" in host_side:
                            port = host_side.rsplit(":", 1)[-1]
                            if port.isdigit():
                                add(f"http://localhost:{port}")

        return candidates

    def _discover_running_url(self, console: Console | None = None) -> str | None:
        candidates = self._discovery_candidates()
        for url in candidates:
            if self._probe_effective(url, strict_identity=True):
                if console is not None and url != self._svc["default_url"]:
                    console.print(f"[green]{self.name} discovered at {url}[/]")
                return url
        return None

    def _wait_until_healthy(self, timeout_s: int = 90) -> bool:
        start = time.time()
        while time.time() - start < timeout_s:
            if self.check():
                return True
            time.sleep(2)
        return False

    def _reconcile_parent_pepers_stack(self, console: Console) -> None:
        if self._project_root is None:
            return
        compose = self._compose_file(self._project_root)
        if compose is None:
            return
        try:
            from services.setup._config import EnvConfig
            from services.setup._docker import _docker_bin, _docker_env
        except Exception:
            return

        docker = _docker_bin()
        if docker is None:
            return

        console.print(
            "[cyan]Updated external service target: reconciling PePeRS docker stack...[/]"
        )
        try:
            subprocess.run(
                [docker, "compose", "up", "-d", "--build", "--force-recreate"],
                cwd=self._project_root,
                check=True,
                text=True,
                env=_docker_env(),
            )
        except subprocess.CalledProcessError:
            env_step = EnvConfig(self._project_root)
            if env_step._retry_reconcile_after_conflict(console, docker):
                return
            console.print(
                "[yellow]Could not auto-reconcile the PePeRS stack after updating "
                f"{self.name}. The new target will apply on the next start.[/]"
            )

    def _maybe_reconcile_parent_pepers_stack(self, console: Console, target_url: str) -> None:
        if self._runtime_dep_needs_sync(target_url):
            self._reconcile_parent_pepers_stack(console)

    def _local_setup_fallback(self) -> tuple[list[str], Path, dict[str, str], str] | None:
        """Return local repo fallback command when CLI is not installed in PATH."""
        repo_name = self._svc.get("local_repo")
        module_name = self._svc.get("local_module")
        if not isinstance(repo_name, str) or not isinstance(module_name, str):
            return None

        # Prefer a sibling repo next to pepers, but fall back to CWD parent when run elsewhere.
        pepers_root = self._project_root or Path(__file__).resolve().parents[2]
        candidate_roots = [
            pepers_root.parent / repo_name,
            Path.cwd().resolve().parent / repo_name,
        ]
        repo_dir = next((p for p in candidate_roots if p.exists()), None)
        if repo_dir is None:
            return None

        env = {"PYTHONHASHSEED": "0"}
        if self._svc.get("local_module_needs_pythonpath"):
            env["PYTHONPATH"] = str(repo_dir)
        venv_python = repo_dir / ".venv" / "bin" / "python"
        if venv_python.exists():
            cmd = [str(venv_python), "-m", module_name]
            display = f"{venv_python} -m {module_name}"
            return cmd, repo_dir, env, display

        # Fresh clone path: run through uv even before local .venv exists.
        if shutil.which("uv") is not None:
            if not (repo_dir / ".venv").exists():
                print(f"Initializing .venv for {repo_name}...")
                subprocess.run(["uv", "sync"], cwd=repo_dir, check=False)
            cmd = ["uv", "run", "python", "-m", module_name]
            display = f"uv run python -m {module_name}"
            return cmd, repo_dir, env, display

        return None

    def _ensure_local_repo(self, console: Console) -> Path | None:
        repo_name = self._svc.get("local_repo")
        if not isinstance(repo_name, str):
            return None
        base = (self._project_root or Path(__file__).resolve().parents[2]).parent
        target = base / repo_name
        if target.exists():
            return target

        if not shutil.which("git"):
            console.print(f"[red]git is not installed. Cannot clone {repo_name}.[/]")
            return None

        clone_url = f"https://github.com/gptcompany/{repo_name}.git"
        if not _ask_confirm_safe(
            f"{repo_name} repo not found. Clone {clone_url} now?",
            default=True,
        ):
            return None
        try:
            result = subprocess.run(
                ["git", "clone", clone_url, str(target)],
                check=False,
            )
        except OSError as exc:
            console.print(f"[red]Failed to launch git clone:[/] {exc}")
            return None
        if result.returncode != 0:
            console.print(f"[red]git clone failed for {clone_url}[/]")
            return None
        return target

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
        configured = self._url()
        if self._probe_effective(configured, timeout=5, strict_identity=True):
            self._active_url = configured
            return True
        discovered = self._discover_running_url()
        if discovered:
            self._active_url = discovered
            # Keep aggregated checks aligned with discovered healthy endpoint.
            self._persist_url_silent(discovered)
            return True
        return False

    def install(self, console: Console) -> bool:
        if self._svc.get("guided_install"):
            return self._install_guided(console)
        return self._install_legacy(console)

    def _install_guided(self, console: Console) -> bool:
        current_url = self._url()
        if self._auto_rehome_host_only_url(console, preferred_url=current_url):
            current_url = self._url()
        if self._probe_effective(current_url, strict_identity=True):
            console.print(f"[green]{self.name} is reachable at {current_url}[/]")
            self._maybe_reconcile_parent_pepers_stack(console, current_url)
            return True

        console.print(f"[yellow]{self.name} is not reachable at {current_url}[/]")
        while True:
            action = _ask_select_safe(
                f"How should setup proceed for {self.name}?",
                [
                    "Use default service URL",
                    "Auto-discover service URL",
                    "Enter custom URL/port",
                    "Install/start service now (recommended)",
                    "Show setup help",
                    "Skip for now",
                ],
                default="Install/start service now (recommended)",
            )

            if action == "Skip for now" or action is None:
                return False

            if action == "Show setup help":
                self.help(console)
                continue

            if action == "Use default service URL":
                default_url = self._svc["default_url"].rstrip("/")
                self._active_url = default_url
                if _ask_confirm_safe(
                    f"Save default URL {default_url} to .env?",
                    default=True,
                ):
                    self._persist_url(default_url, console)
                else:
                    self._set_runtime_url(default_url)
                if self._auto_rehome_host_only_url(console, preferred_url=default_url):
                    continue
                if self._probe_effective(default_url, strict_identity=True):
                    self._maybe_reconcile_parent_pepers_stack(console, default_url)
                    return True
                console.print(
                    f"[yellow]{self.name} not reachable at {default_url}{self._svc['health_path']}[/]"
                )
                continue

            if action == "Auto-discover service URL":
                discovered = self._discover_running_url(console)
                if not discovered:
                    console.print(f"[yellow]No running {self.name} endpoint discovered.[/]")
                    continue
                self._active_url = discovered
                if _ask_confirm_safe(
                    f"Save {discovered} to .env?",
                    default=True,
                ):
                    self._persist_url(discovered, console)
                else:
                    self._set_runtime_url(discovered)
                self._maybe_reconcile_parent_pepers_stack(console, discovered)
                return True

            if action == "Enter custom URL/port":
                raw = _ask_text_safe(
                    "Enter full URL (e.g. http://localhost:9999) or just port (e.g. 9999):",
                    default=self._url(),
                )
                if not raw:
                    continue
                custom = self._normalize_user_url(raw)
                self._active_url = custom
                if self._auto_rehome_host_only_url(console, preferred_url=custom):
                    continue
                if self._probe_effective(custom, strict_identity=True):
                    if _ask_confirm_safe(
                        f"Save {custom} to .env?",
                        default=True,
                    ):
                        self._persist_url(custom, console)
                    else:
                        self._set_runtime_url(custom)
                    self._maybe_reconcile_parent_pepers_stack(console, custom)
                    return True
                console.print(
                    f"[yellow]{self.name} not reachable at {custom}{self._svc['health_path']}[/]"
                )
                if _ask_confirm_safe(
                    f"Keep {custom} as target URL for next install/start attempt and save to .env?",
                    default=True,
                ):
                    self._persist_url(custom, console)
                else:
                    self._set_runtime_url(custom)
                continue

            # Install/start selected.
            if self._run_setup_install(console):
                if self._wait_until_healthy():
                    self._maybe_reconcile_parent_pepers_stack(console, self._url())
                    return True
                console.print(
                    f"[yellow]{self.name} setup completed but health endpoint is still unreachable.[/]"
                )
            else:
                console.print(f"[yellow]{self.name} setup did not complete successfully.[/]")

    def _install_legacy(self, console: Console) -> bool:
        console.print(f"[yellow]{self.name} is not reachable at {self._url()}[/]")
        setup_cmd = self._svc.get("setup_cmd")
        if isinstance(setup_cmd, str) and shutil.which(setup_cmd):
            if _ask_confirm_safe(
                f"Launch {setup_cmd} now?",
                default=True,
            ):
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
                if _ask_confirm_safe(
                    f"Launch local setup wizard from {cwd.name}? ({display})",
                    default=True,
                ):
                    run_env = os.environ.copy()
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
        return False

    def _run_setup_install(self, console: Console) -> bool:
        setup_cmd = self._svc.get("setup_cmd")
        runtime_env = os.environ.copy()
        runtime_env.update(self._runtime_env_overrides())
        if isinstance(setup_cmd, str) and shutil.which(setup_cmd):
            console.print(f"[cyan]Launching {setup_cmd}...[/]")
            try:
                result = subprocess.run([setup_cmd], env=runtime_env, check=False)
            except OSError as exc:
                console.print(f"[red]Failed to launch {setup_cmd}:[/] {exc}")
            else:
                if result.returncode == 0:
                    # Child setup may report success while Docker keeps stale containers.
                    # Reconcile compose stack automatically when available.
                    self._auto_reconcile_docker_service(console, Path.cwd(), runtime_env)
                    return True
                # Child setup may return non-zero when optional steps are left pending.
                # Treat it as success if service is actually reachable.
                if self.check():
                    console.print(
                        f"[yellow]{setup_cmd} exited {result.returncode}, "
                        f"but {self.name} is reachable. Continuing.[/]"
                    )
                    self._auto_reconcile_docker_service(console, Path.cwd(), runtime_env)
                    return True
                console.print(f"[red]{setup_cmd} failed (exit {result.returncode})[/]")

        fallback = self._local_setup_fallback()
        if fallback is None:
            repo = self._ensure_local_repo(console)
            if repo is not None:
                fallback = self._local_setup_fallback()

        if fallback is not None:
            cmd, cwd, env_extra, display = fallback
            self._refresh_repo_best_effort(cwd, console)
            console.print(f"[cyan]Launching local setup: {display}[/]")
            run_env = os.environ.copy()
            if "PYTHONPATH" in env_extra and run_env.get("PYTHONPATH"):
                env_extra = env_extra.copy()
                env_extra["PYTHONPATH"] = (
                    f"{env_extra['PYTHONPATH']}:{run_env['PYTHONPATH']}"
                )
            run_env.update(env_extra)
            run_env.update(self._runtime_env_overrides())
            try:
                result = subprocess.run(cmd, cwd=cwd, env=run_env, check=False)
            except OSError as exc:
                console.print(f"[red]Failed to launch local setup:[/] {exc}")
            else:
                if result.returncode == 0:
                    # Child setup may report success while Docker keeps stale containers.
                    # Reconcile compose stack automatically when available.
                    self._auto_reconcile_docker_service(console, cwd, run_env)
                    return True
                # Child setup may return non-zero when optional steps are left pending.
                # Treat it as success if service is actually reachable.
                if self.check():
                    console.print(
                        f"[yellow]Local setup exited {result.returncode}, "
                        f"but {self.name} is reachable. Continuing.[/]"
                    )
                    self._auto_reconcile_docker_service(console, cwd, run_env)
                    return True
                console.print(f"[red]Local setup failed (exit {result.returncode})[/]")

        console.print(f"[dim]{self._svc['setup_hint']}[/]")
        return False

    def _refresh_repo_best_effort(self, repo_dir: Path, console: Console) -> None:
        """Try to fast-forward local child repo before running its setup."""
        if shutil.which("git") is None:
            return
        if not (repo_dir / ".git").exists():
            return
        try:
            fetch = subprocess.run(
                ["git", "-C", str(repo_dir), "fetch", "origin"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if fetch.returncode != 0:
                return
            branch = subprocess.run(
                ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            current = branch.stdout.strip() or "main"
            pull = subprocess.run(
                ["git", "-C", str(repo_dir), "pull", "--ff-only", "origin", current],
                check=False,
                capture_output=True,
                text=True,
                timeout=25,
            )
            if pull.returncode == 0 and ("Already up to date" not in (pull.stdout or "")):
                console.print(f"[dim]Updated {repo_dir.name} before setup.[/]")
        except Exception:
            # Best effort only.
            return

    def _compose_file(self, repo_dir: Path) -> Path | None:
        for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            candidate = repo_dir / name
            if candidate.exists():
                return candidate
        return None

    def _auto_reconcile_docker_service(
        self,
        console: Console,
        repo_dir: Path,
        run_env: dict[str, str],
    ) -> None:
        """Best-effort docker reconcile after child setup success.

        This prevents stale containers/images from surviving repeated setup runs.
        """
        if shutil.which("docker") is None:
            return
        compose = self._compose_file(repo_dir)
        if compose is None:
            return

        cmd_base = ["docker", "compose"]
        env = os.environ.copy()
        env.update(run_env)

        # Use dotenvx when available in child repo to honor encrypted .env files.
        dotenvx = shutil.which("dotenvx")
        env_file = repo_dir / ".env"
        if dotenvx and env_file.exists():
            cmd_base = ["dotenvx", "run", "-f", str(env_file), "--", "docker", "compose"]

        console.print(
            f"[cyan]Reconciling {self.name} docker stack ({repo_dir.name}/{compose.name})...[/]"
        )
        console.print("[dim]Running compose up with --build --force-recreate.[/]")
        try:
            res = subprocess.run(
                [*cmd_base, "up", "-d", "--build", "--force-recreate"],
                cwd=repo_dir,
                env=env,
                check=False,
            )
            if res.returncode == 0:
                return

            console.print(
                "[yellow]Compose reconcile with rebuild failed; retrying plain up -d.[/]"
            )
            subprocess.run(
                [*cmd_base, "up", "-d"],
                cwd=repo_dir,
                env=env,
                check=False,
            )
        except Exception:
            # Best effort only; main flow still relies on health verification.
            return

    def help(self, console: Console) -> None:
        console.print(f"[bold]{self.name} setup help[/]")
        console.print(f"Target URL: [cyan]{self._url()}[/]")
        env_urls = self._svc.get("env_urls")
        if isinstance(env_urls, list) and env_urls:
            console.print("Environment overrides:")
            for key in env_urls:
                if isinstance(key, str):
                    console.print(f"  - {key}")
        console.print("\n[bold]Practical Instructions:[/]")
        console.print(f"{self._svc['setup_hint']}")

    def verify(self) -> bool:
        return self.check()


class ExternalServicePersistenceCheck:
    """Ensure a reachable external service survives reboot."""

    def __init__(self, svc: dict, project_root: Path | None = None) -> None:
        self._svc = svc
        self._health = ExternalServiceCheck(svc, project_root=project_root)
        self.name = f"{svc['name']} boot persistence"
        self.description = "Reboot survival via systemd/docker/@reboot"

    def check(self) -> bool:
        if _is_macos():
            # On macOS we don't enforce persistence as a blocking requirement.
            return True
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
        if _is_macos():
            console.print("[dim]Recommended (macOS):[/]")
            console.print(
                "  Use launchctl with the service's launchd plist "
                "(see rag-service/cas-service docs)."
            )
            console.print(
                "  Or run via Docker with restart policy enabled."
            )
            return True

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


def get_all_steps(project_root: Path | None = None) -> list:
    steps: list = []
    for svc in _EXTERNAL_SERVICES:
        steps.append(ExternalServiceCheck(svc, project_root=project_root))
        steps.append(ExternalServicePersistenceCheck(svc, project_root=project_root))
    return steps
