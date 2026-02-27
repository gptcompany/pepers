"""PePeRS Setup Wizard -- CLI entry point.

Usage:
    pepers-setup              # interactive menu (all steps)
    pepers-setup check        # prerequisites only
    pepers-setup config       # .env configuration only
    pepers-setup services     # external services check only
    pepers-setup docker       # Docker Compose only
    pepers-setup down         # stop and remove containers
    pepers-setup verify       # aggregated health check only
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

BANNER = r"""
    ____       ____      ____  ____
   / __ \___  / __ \___  / _ \/ __/
  / /_/ / _ \/ /_/ / _ \/ , _/\ \
 / .___/\___/ .___/\___/_/|_/___/
/_/        /_/    Setup Wizard
"""

WELCOME_GUIDE = """\
[bold]Full setup -- this wizard will:[/]

  1. Check system prerequisites  (Python, uv, SQLite, dotenvx)
  2. Install CLI tools           (Node.js, Ollama, Claude/Gemini/Codex CLI)
  3. Configure environment       (service ports, URLs, defaults)
  4. Setup CAS Service           (launches cas-setup if needed)
  5. Setup RAG Service           (launches rag-setup if needed)
  6. Configure MCP integration   (auto-add to Claude Desktop)
  7. Docker + Health check       (start services, verify everything)

  Press Enter to accept defaults. Optional steps can be skipped.
"""


def _print_usage(console: Console) -> None:
    console.print(
        "Usage: pepers-setup [all|check|config|services|docker|down|verify|help]",
        markup=False,
    )


def _project_root() -> Path:
    """Find the project root (directory containing pyproject.toml)."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent.parent, Path.cwd()):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return Path.cwd()


def _all_steps(root: Path) -> list:
    """Build full step list for interactive menu."""
    from services.setup._checks import get_all_steps as checks_steps
    from services.setup._cli_tools import get_all_steps as cli_tools_steps
    from services.setup._config import EnvConfig
    from services.setup._docker import get_all_steps as docker_steps
    from services.setup._mcp_config import McpConfigStep
    from services.setup._services import get_all_steps as services_steps
    from services.setup._verify import AggregatedHealthCheck

    return [
        *checks_steps(root),
        *cli_tools_steps(),
        EnvConfig(root),
        *services_steps(),
        McpConfigStep(),
        *docker_steps(root),
        AggregatedHealthCheck(),
    ]


def _check_steps(root: Path) -> list:
    from services.setup._checks import get_all_steps

    return get_all_steps(root)


def _config_steps(root: Path) -> list:
    from services.setup._config import EnvConfig

    return [EnvConfig(root)]


def _services_steps(_: Path) -> list:
    from services.setup._services import get_all_steps

    return get_all_steps()


def _docker_steps(root: Path) -> list:
    from services.setup._docker import get_all_steps

    return get_all_steps(root)


def _down_steps(root: Path) -> list:
    from services.setup._docker import get_down_steps

    return get_down_steps(root)


def _verify_steps(_: Path) -> list:
    from services.setup._verify import AggregatedHealthCheck

    return [AggregatedHealthCheck()]


SUBCOMMANDS: dict[str, Callable[[Path], list]] = {
    "check": _check_steps,
    "config": _config_steps,
    "services": _services_steps,
    "docker": _docker_steps,
    "down": _down_steps,
    "verify": _verify_steps,
}


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

    from services.setup._runner import run_interactive_menu, run_steps

    if command == "all":
        console.print(WELCOME_GUIDE)
        steps = _all_steps(root)
        ok = run_interactive_menu(steps, console)
        return 0 if ok else 1
    elif command in SUBCOMMANDS:
        steps = SUBCOMMANDS[command](root)
    else:
        console.print(f"[red]Unknown command: {command}[/]")
        _print_usage(console)
        return 1

    ok = run_steps(steps, console)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
