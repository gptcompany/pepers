"""Step: system prerequisites (Python, uv, SQLite, dotenvx, disk space)."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from rich.console import Console


class PythonCheck:
    name = "Python >= 3.10"

    def check(self) -> bool:
        return sys.version_info >= (3, 10)

    def install(self, console: Console) -> bool:
        console.print(
            "[yellow]Python >= 3.10 is required.[/]\n"
            "Install from https://www.python.org/downloads/ "
            "or use your system package manager."
        )
        return False  # can't auto-install Python

    def verify(self) -> bool:
        return self.check()


class UvCheck:
    name = "uv (package manager)"

    def check(self) -> bool:
        return shutil.which("uv") is not None

    def install(self, console: Console) -> bool:
        console.print("[cyan]Installing uv...[/]")
        try:
            subprocess.run(
                ["pip", "install", "uv"],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            console.print(
                "[yellow]Could not install uv via pip.[/]\n"
                "Try: curl -LsSf https://astral.sh/uv/install.sh | sh"
            )
            return False

    def verify(self) -> bool:
        return shutil.which("uv") is not None


class SQLiteCheck:
    name = "SQLite >= 3.35 (WAL mode)"

    def check(self) -> bool:
        version = sqlite3.sqlite_version_info
        return version >= (3, 35, 0)

    def install(self, console: Console) -> bool:
        console.print(
            f"[yellow]SQLite {sqlite3.sqlite_version} found, need >= 3.35.[/]\n"
            "Upgrade your system SQLite or rebuild Python against a newer version."
        )
        return False

    def verify(self) -> bool:
        return self.check()


class VenvCheck:
    name = "Virtual environment (.venv)"

    def __init__(self, project_root: Path) -> None:
        self._root = project_root

    def check(self) -> bool:
        venv = self._root / ".venv"
        return venv.is_dir() and (venv / "bin" / "python").exists()

    def install(self, console: Console) -> bool:
        console.print("[cyan]Creating virtual environment with uv...[/]")
        try:
            subprocess.run(
                ["uv", "sync"],
                cwd=self._root,
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            console.print(f"[red]uv sync failed:[/] {exc}")
            return False

    def verify(self) -> bool:
        return self.check()


class DotenvxCheck:
    name = "dotenvx (secret management)"

    def check(self) -> bool:
        return shutil.which("dotenvx") is not None

    def install(self, console: Console) -> bool:
        console.print("[cyan]Installing dotenvx...[/]")
        try:
            subprocess.run(
                ["sh", "-c", "curl -sfS https://dotenvx.sh | sh"],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            console.print(
                "[yellow]Auto-install failed.[/]\n"
                "See https://dotenvx.com/docs/install"
            )
            return False

    def verify(self) -> bool:
        return shutil.which("dotenvx") is not None


class DiskSpaceCheck:
    name = "Disk space (data/ directory)"
    _min_mb = 500

    def __init__(self, project_root: Path) -> None:
        self._root = project_root

    def check(self) -> bool:
        data_dir = self._root / "data"
        target = data_dir if data_dir.exists() else self._root
        usage = shutil.disk_usage(target)
        free_mb = usage.free / (1024 * 1024)
        return free_mb >= self._min_mb

    def install(self, console: Console) -> bool:
        data_dir = self._root / "data"
        target = data_dir if data_dir.exists() else self._root
        usage = shutil.disk_usage(target)
        free_mb = usage.free / (1024 * 1024)
        console.print(
            f"[yellow]Only {free_mb:.0f} MB free, need >= {self._min_mb} MB.[/]\n"
            "Free up disk space and retry."
        )
        return False

    def verify(self) -> bool:
        return self.check()


def get_all_steps(project_root: Path) -> list:
    return [
        PythonCheck(),
        UvCheck(),
        SQLiteCheck(),
        VenvCheck(project_root),
        DotenvxCheck(),
        DiskSpaceCheck(project_root),
    ]
