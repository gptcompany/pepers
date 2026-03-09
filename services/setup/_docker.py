"""Step: Docker Compose setup (optional)."""

from __future__ import annotations

import shutil
import subprocess
import time
from platform import system
from pathlib import Path

from rich.console import Console


def _docker_bin() -> str | None:
    docker = shutil.which("docker")
    if docker:
        return docker
    if system() == "Darwin":
        fallback = Path("/usr/local/bin/docker")
        if fallback.exists():
            return str(fallback)
    return None


class DockerCheck:
    name = "Docker"
    description = "Container runtime for local service stack"

    def check(self) -> bool:
        return _docker_bin() is not None

    def install(self, console: Console) -> bool:
        console.print(
            "[yellow]Docker is not installed.[/]\n"
            "Install from https://docs.docker.com/get-docker/"
        )
        if system() == "Darwin":
            console.print(
                "[dim]On macOS: install Docker Desktop and launch it once.[/]"
            )
        return False

    def verify(self) -> bool:
        return self.check()


class DockerComposeCheck:
    name = "Docker Compose"
    description = "Compose subcommand for multi-service orchestration"

    def check(self) -> bool:
        docker = _docker_bin()
        if docker is None:
            return False
        try:
            subprocess.run(
                [docker, "compose", "version"],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def install(self, console: Console) -> bool:
        console.print(
            "[yellow]docker compose not available.[/]\n"
            "Ensure Docker Desktop or docker-compose-plugin is installed."
        )
        if system() == "Darwin":
            console.print(
                "[dim]On macOS: Docker Compose is bundled with Docker Desktop.[/]"
            )
        return False


def _docker_daemon_ready() -> bool:
    docker = _docker_bin()
    if docker is None:
        return False
    try:
        subprocess.run(
            [docker, "info"],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _wait_for_docker_daemon(timeout_s: int = 60) -> bool:
    start = time.time()
    while time.time() - start < timeout_s:
        if _docker_daemon_ready():
            return True
        time.sleep(2)
    return False


def _maybe_start_docker_desktop(console: Console) -> None:
    if system() != "Darwin":
        return
    try:
        import questionary

        if questionary.confirm(
            "Docker Desktop is not running. Open it now?",
            default=True,
        ).ask():
            docker_app = Path("/Applications/Docker.app")
            if docker_app.exists():
                subprocess.run(["open", "-a", "Docker"], check=False)
            else:
                console.print(
                    "[yellow]Docker Desktop not found at /Applications/Docker.app.[/]"
                )
                console.print(
                    "[dim]Install from https://docs.docker.com/desktop/install/mac-install/[/]"
                )
                console.print(
                    "[dim]Or via Homebrew: brew install --cask docker[/]"
                )
                console.print(
                    "[dim]macOS 12+: Docker Desktop installs under /Applications (requires admin password).[/]"
                )
                return
            console.print("[dim]Waiting for Docker Desktop...[/]")
            if _wait_for_docker_daemon(90):
                console.print("[green]Docker Desktop is ready.[/]")
            else:
                console.print("[yellow]Docker Desktop did not become ready yet.[/]")
    except Exception:
        # Non-interactive fallback
        console.print(
            "[yellow]Docker Desktop not running. Start it and retry.[/]"
        )


class DockerComposeUp:
    name = "Docker Compose services"
    description = "Start local containers from compose file"
    auto_reconcile_when_configured = True

    def __init__(self, project_root: Path) -> None:
        self._root = project_root

    def _compose_file(self) -> Path | None:
        for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            p = self._root / name
            if p.exists():
                return p
        return None

    def check(self) -> bool:
        if self._compose_file() is None:
            return True  # no compose file = nothing to do
        docker = _docker_bin()
        if docker is None:
            return False
        try:
            result = subprocess.run(
                [docker, "compose", "ps", "--format", "json"],
                cwd=self._root,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0 and len(result.stdout.strip()) > 0
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def install(self, console: Console) -> bool:
        compose = self._compose_file()
        if compose is None:
            console.print("[dim]No docker-compose file found, skipping.[/]")
            return True

        if not _docker_daemon_ready():
            console.print("[yellow]Docker daemon is not running.[/]")
            if system() == "Darwin":
                _maybe_start_docker_desktop(console)
            else:
                console.print(
                    "[dim]Try: sudo systemctl start docker (Linux)[/]"
                )
            if not _docker_daemon_ready():
                return False

        console.print(f"[cyan]Running docker compose up -d ({compose.name})...[/]")
        console.print(
            "[dim]This may take a few minutes; Docker will print progress below.[/]"
        )
        docker = _docker_bin()
        if docker is None:
            console.print("[red]docker binary not found in PATH.[/]")
            return False
        try:
            subprocess.run(
                [docker, "compose", "up", "-d", "--build", "--force-recreate"],
                cwd=self._root,
                check=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError:
            console.print(
                "[yellow]Compose rebuild failed; retrying with plain up -d...[/]"
            )
        try:
            subprocess.run(
                [docker, "compose", "up", "-d"],
                cwd=self._root,
                check=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]docker compose up failed:[/] {exc}")
            if "docker.sock" in (exc.stderr or ""):
                console.print(
                    "[yellow]Docker is installed but not running. Start Docker Desktop and retry.[/]"
                )
            return False

    def verify(self) -> bool:
        return self.check()


class DockerBootCheck:
    name = "Docker boot persistence"
    description = "Ensure Docker starts on system boot"

    def check(self) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "is-enabled", "docker"],
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() == "enabled"
        except FileNotFoundError:
            # No systemd (e.g. macOS) — skip gracefully
            return True

    def install(self, console: Console) -> bool:
        console.print(
            "[yellow]Docker is not enabled at boot.[/]\n"
            "Run: [bold]sudo systemctl enable docker[/]"
        )
        return False

    def verify(self) -> bool:
        return self.check()


class DockerComposeDown:
    name = "Docker Compose teardown"
    description = "Stop and remove local containers"

    def __init__(self, project_root: Path) -> None:
        self._root = project_root

    def check(self) -> bool:
        docker = _docker_bin()
        if docker is None:
            return True  # nothing to tear down if docker unavailable
        try:
            result = subprocess.run(
                [docker, "compose", "ps", "--quiet"],
                cwd=self._root,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0 and len(result.stdout.strip()) == 0
        except (subprocess.CalledProcessError, FileNotFoundError):
            return True  # No compose / no docker → nothing to tear down

    def install(self, console: Console) -> bool:
        docker = _docker_bin()
        if docker is None:
            console.print("[yellow]docker not found; nothing to tear down.[/]")
            return True
        console.print("[cyan]Running docker compose down...[/]")
        try:
            subprocess.run(
                [docker, "compose", "down"],
                cwd=self._root,
                check=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]docker compose down failed:[/] {exc}")
            return False

    def verify(self) -> bool:
        return self.check()


def get_down_steps(project_root: Path) -> list:
    return [DockerComposeDown(project_root)]


def get_all_steps(project_root: Path) -> list:
    return [
        DockerCheck(),
        DockerComposeCheck(),
        DockerBootCheck(),
        DockerComposeUp(project_root),
    ]
