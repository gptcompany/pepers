"""Step: Docker Compose setup (optional)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from rich.console import Console


class DockerCheck:
    name = "Docker"
    description = "Container runtime for local service stack"

    def check(self) -> bool:
        return shutil.which("docker") is not None

    def install(self, console: Console) -> bool:
        console.print(
            "[yellow]Docker is not installed.[/]\n"
            "Install from https://docs.docker.com/get-docker/"
        )
        return False

    def verify(self) -> bool:
        return self.check()


class DockerComposeCheck:
    name = "Docker Compose"
    description = "Compose subcommand for multi-service orchestration"

    def check(self) -> bool:
        try:
            subprocess.run(
                ["docker", "compose", "version"],
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
        return False

    def verify(self) -> bool:
        return self.check()


class DockerComposeUp:
    name = "Docker Compose services"
    description = "Start local containers from compose file"

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
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "json"],
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

        console.print(f"[cyan]Running docker compose up -d ({compose.name})...[/]")
        try:
            subprocess.run(
                ["docker", "compose", "up", "-d"],
                cwd=self._root,
                check=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]docker compose up failed:[/] {exc}")
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
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "--quiet"],
                cwd=self._root,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0 and len(result.stdout.strip()) == 0
        except (subprocess.CalledProcessError, FileNotFoundError):
            return True  # No compose / no docker → nothing to tear down

    def install(self, console: Console) -> bool:
        console.print("[cyan]Running docker compose down...[/]")
        try:
            subprocess.run(
                ["docker", "compose", "down"],
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
