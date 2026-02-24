"""PePeRS Setup Wizard — CLI entry point.

Usage:
    pepers-setup              # full wizard (all steps)
    pepers-setup check        # prerequisites only
    pepers-setup config       # .env configuration only
    pepers-setup services     # external services check only
    pepers-setup docker       # Docker Compose only
    pepers-setup verify       # aggregated health check only
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

BANNER = r"""
    ____       ____      ____  ____
   / __ \___  / __ \___  / _ \/ __/
  / /_/ / _ \/ /_/ / _ \/ , _/\ \
 / .___/\___/ .___/\___/_/|_/___/
/_/        /_/    Setup Wizard
"""


def _print_usage(console: Console) -> None:
    console.print(
        "Usage: pepers-setup [all|check|config|services|docker|verify|help]",
        markup=False,
    )


def _project_root() -> Path:
    """Find the project root (directory containing pyproject.toml)."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent.parent, Path.cwd()):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    console = Console()
    root = _project_root()

    console.print(f"[bold green]{BANNER}[/]")
    console.print(f"[dim]Project root: {root}[/]\n")

    command = args[0] if args else "all"
    if command in {"-h", "--help", "help"}:
        _print_usage(console)
        return 0

    from services.setup._runner import run_steps

    if command == "check":
        from services.setup._checks import get_all_steps
        steps = get_all_steps(root)
    elif command == "config":
        from services.setup._config import EnvConfig
        steps = [EnvConfig(root)]
    elif command == "services":
        from services.setup._services import get_all_steps
        steps = get_all_steps()
    elif command == "docker":
        from services.setup._docker import get_all_steps
        steps = get_all_steps(root)
    elif command == "verify":
        from services.setup._verify import AggregatedHealthCheck
        steps = [AggregatedHealthCheck()]
    elif command == "all":
        from services.setup._checks import get_all_steps as checks_steps
        from services.setup._config import EnvConfig
        from services.setup._docker import get_all_steps as docker_steps
        from services.setup._services import get_all_steps as services_steps
        from services.setup._verify import AggregatedHealthCheck

        steps = [
            *checks_steps(root),
            EnvConfig(root),
            *services_steps(),
            *docker_steps(root),
            AggregatedHealthCheck(),
        ]
    else:
        console.print(f"[red]Unknown command: {command}[/]")
        _print_usage(console)
        return 1

    ok = run_steps(steps, console)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
