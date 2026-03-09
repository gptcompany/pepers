"""PePeRS Setup Wizard -- CLI entry point.

Usage:
    pepers-setup              # choose mode (default)
    pepers-setup easy         # same as above
    pepers-setup walkthrough  # linear, step-by-step prompts
    pepers-setup guided       # interactive menu (all steps)
    pepers-setup all          # alias for guided (backward compat)
    pepers-setup --non-interactive   # quick start, no prompts
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
  ____  _____ ____  _____ ____  ____
 |  _ \| ____|  _ \| ____|  _ \/ ___|
 | |_) |  _| | |_) |  _| | |_) \___ \
 |  __/| |___|  __/| |___|  _ < ___) |
 |_|   |_____|_|   |_____|_| \_\____/
              PePeRS Setup Wizard
"""

WELCOME_GUIDE = """\
[bold]Full setup -- this wizard will:[/]

  1. Check system prerequisites  (Python, uv, SQLite, dotenvx)
  2. Install CLI tools           (Node.js, Ollama, Claude/Gemini/Codex CLI)
  3. Configure environment       (service ports, URLs, defaults)
  4. Setup CAS Service           (launches cas-setup if needed)
  5. Setup RAG Service           (launches rag-setup if needed)
  6. Configure MCP integration   (Claude Code/Desktop target selection)
  7. Docker + Health check       (start services, verify everything)

  Press Enter to accept defaults. Optional steps can be skipped.
"""


def _print_usage(console: Console) -> None:
    console.print(
        "Usage: pepers-setup [easy|walkthrough|guided|all|check|config|services|docker|down|verify|help|--non-interactive]",
        markup=False,
    )
    console.print(
        "[dim]  (default)  choose — select quick / walkthrough / guided\n"
        "  --non-interactive quick start (no prompts)\n"
        "  guided     interactive menu with free navigation\n"
        "  walkthrough step-by-step prompts (linear)\n"
        "  all        alias for guided (backward compat)[/]"
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
        *services_steps(root),
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


def _services_steps(root: Path) -> list:
    from services.setup._services import get_all_steps

    return get_all_steps(root)


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


def _tag_tier(
    steps: list, tier: str, tier_map: dict[str, str],
) -> list:
    """Register each step's name in tier_map and return the steps unchanged."""
    for step in steps:
        tier_map[step.name] = tier
    return steps


def _easy_mode(root: Path, console: Console) -> int:
    """Non-interactive setup: safe defaults, Docker-first, structured verdict."""
    from services.setup._checks import (
        DiskSpaceCheck,
        PythonCheck,
        SQLiteCheck,
        UvCheck,
        VenvCheck,
    )
    from services.setup._config import EnvConfig
    from services.setup._docker import DockerCheck, DockerComposeCheck, DockerComposeUp
    from services.setup._runner import run_noninteractive
    from services.setup._services import ExternalServiceCheck, _EXTERNAL_SERVICES
    from services.setup._verify import (
        AggregatedHealthCheck,
        Readiness,
        TIER_CORE,
        TIER_EXTERNAL,
        compute_verdict,
        print_verdict,
    )

    all_results: list[tuple[str, str]] = []
    tier_map: dict[str, str] = {}

    # ── Core prerequisites ───────────────────────────────────
    core_steps = _tag_tier([
        PythonCheck(),
        UvCheck(),
        SQLiteCheck(),
        VenvCheck(root),
        DiskSpaceCheck(root),
    ], TIER_CORE, tier_map)
    all_results.extend(run_noninteractive(core_steps, console))

    # ── EnvConfig (auto-generate .env with defaults) ─────────
    env_cfg = EnvConfig(root)
    tier_map[env_cfg.name] = TIER_CORE
    if env_cfg.check():
        console.print(f"  [green]\u2705 {env_cfg.name}[/] \u2014 already configured")
        all_results.append((env_cfg.name, "ok"))
    else:
        ok = env_cfg.install_defaults(console)
        all_results.append((env_cfg.name, "ok" if ok else "failed"))

    # ── Docker ───────────────────────────────────────────────
    docker_steps = _tag_tier([
        DockerCheck(),
        DockerComposeCheck(),
        DockerComposeUp(root),
    ], TIER_CORE, tier_map)
    all_results.extend(run_noninteractive(docker_steps, console))

    # ── External services (check-only, no install) ───────────
    external_steps = _tag_tier(
        [ExternalServiceCheck(svc, project_root=root) for svc in _EXTERNAL_SERVICES],
        TIER_EXTERNAL, tier_map,
    )
    all_results.extend(
        run_noninteractive(external_steps, console, check_only=True)
    )

    # ── Health table (informational) ─────────────────────────
    console.print()
    AggregatedHealthCheck().install(console)

    # ── Verdict ──────────────────────────────────────────────
    verdict = compute_verdict(all_results, tier_map)
    print_verdict(verdict, console)

    return 0 if verdict.readiness != Readiness.NOT_READY else 1


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    console = Console()
    root = _project_root()

    console.print(f"[bold green]{BANNER}[/]")
    console.print(f"[dim]Project root: {root}[/]\n")
    console.print(
        "[dim]Tip: use --non-interactive for a quick start without prompts.[/]\n"
    )

    if "--non-interactive" in args:
        command = "easy"
        args = [a for a in args if a != "--non-interactive"]
    else:
        command = args[0] if args else "choose"
    if not sys.stdin.isatty() and command in {"walkthrough", "choose"}:
        command = "easy"
    if command in {"-h", "--help", "help"}:
        _print_usage(console)
        return 0

    if command == "choose":
        import questionary

        choice = questionary.select(
            "How would you like to set up PePeRS?",
            choices=[
                questionary.Choice(
                    "Quick start (automatic)",
                    value="easy",
                ),
                questionary.Choice(
                    "Step-by-step (guided prompts)",
                    value="walkthrough",
                ),
                questionary.Choice(
                    "Interactive menu (pick steps)",
                    value="guided",
                ),
                questionary.Choice("Exit", value="exit"),
            ],
        ).ask()
        if choice in {None, "exit"}:
            console.print("[yellow]Setup aborted by user.[/]")
            return 1
        command = choice

    if command == "easy":
        return _easy_mode(root, console)

    if command == "walkthrough":
        from services.setup._runner import run_steps

        console.print(WELCOME_GUIDE)
        steps = _all_steps(root)
        ok = run_steps(steps, console)
        return 0 if ok else 1

    if command in {"all", "guided"}:
        from services.setup._runner import run_interactive_menu

        console.print(WELCOME_GUIDE)
        steps = _all_steps(root)
        ok = run_interactive_menu(steps, console)
        return 0 if ok else 1

    if command in SUBCOMMANDS:
        from services.setup._runner import run_steps

        steps = SUBCOMMANDS[command](root)
        ok = run_steps(steps, console)
        return 0 if ok else 1

    console.print(f"[red]Unknown command: {command}[/]")
    _print_usage(console)
    return 1


if __name__ == "__main__":
    sys.exit(main())
