"""Cascading step runner for setup wizards."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import questionary
from rich.console import Console


class SetupStep(Protocol):
    """Contract for a setup step: detect -> install -> verify."""

    name: str
    description: str

    def check(self) -> bool:
        """Return True if already configured/available."""
        ...

    def install(self, console: Console) -> bool:
        """Attempt to install/configure. Return True on success."""
        ...

    def verify(self) -> bool:
        """Post-install health check. Return True if OK."""
        ...


def _print_step_help(step: SetupStep, console: Console) -> None:
    if hasattr(step, "help") and callable(getattr(step, "help")):
        try:
            step.help(console)  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    desc = getattr(step, "description", "")
    if desc:
        console.print(f"[dim]{desc}[/]")


def _run_single_step(step: SetupStep, console: Console, *, force_run: bool = False) -> str:
    """Execute check -> install -> verify for a single step.

    Returns status: "ok" | "skipped" | "failed" | "warn" | "abort".
    """
    with console.status(f"[bold cyan]Checking {step.name}...[/]"):
        is_configured = step.check()

    auto_reconcile_flag = getattr(step, "auto_reconcile_when_configured", False) is True
    if is_configured and not auto_reconcile_flag and not force_run:
        console.print(f"  [green]\u2705 {step.name}[/] \u2014 already configured")
        return "ok"
    if is_configured and not force_run:
        console.print(
            f"  [green]\u2705 {step.name}[/] \u2014 already configured "
            "(running automatic reconcile)"
        )
    if is_configured and force_run:
        console.print(
            f"  [green]\u2705 {step.name}[/] \u2014 already configured "
            "(re-running by user request)"
        )

    if not is_configured:
        if not questionary.confirm(
            f"Configure {step.name}?", default=True
        ).ask():
            console.print(f"  [yellow]\u23ed\ufe0f  {step.name}[/] \u2014 skipped")
            return "skipped"

    success = step.install(console)
    if not success:
        while True:
            action = questionary.select(
                f"{step.name} failed. What to do?",
                choices=[
                    "Show setup help",
                    "Retry",
                    "Skip and continue",
                    "Abort",
                ],
            ).ask()
            if action == "Abort":
                console.print("[bold red]Setup aborted.[/]")
                return "abort"
            if action == "Show setup help":
                _print_step_help(step, console)
                continue
            if action == "Retry":
                success = step.install(console)
                if not success:
                    console.print(
                        f"  [red]\u274c {step.name}[/] \u2014 retry failed, skipping"
                    )
                    return "failed"
                break
            return "skipped"

    if step.verify():
        console.print(f"  [green]\u2705 {step.name}[/] \u2014 verified!")
        return "ok"
    console.print(
        f"  [yellow]\u26a0\ufe0f  {step.name}[/] \u2014 installed but verify failed"
    )
    return "warn"


def run_steps(steps: list[SetupStep], console: Console) -> bool:
    """Execute steps in linear cascade.

    Returns True if all steps succeeded or were skipped by user.
    """
    results: list[tuple[str, str]] = []

    for step in steps:
        status = _run_single_step(step, console)
        results.append((step.name, status))
        if status == "abort":
            return False

    console.print()
    _print_summary(results, console)
    return all(s != "failed" for _, s in results)


def run_interactive_menu(steps: list[SetupStep], console: Console) -> bool:
    """Interactive menu with step status and free navigation.

    Returns True if all steps are ok at exit.
    """
    while True:
        # Refresh status for each step
        statuses: list[tuple[SetupStep, str]] = []
        for step in steps:
            try:
                ok = step.check()
            except Exception:
                ok = False
            if not ok:
                statuses.append((step, "pending"))
                continue
            try:
                verified = step.verify()
            except Exception:
                verified = False
            statuses.append((step, "ok" if verified else "warn"))

        # Build menu choices
        choices: list[questionary.Choice] = []
        for i, (step, status) in enumerate(statuses, 1):
            icon = "\u2705" if status == "ok" else ("\u26a0\ufe0f" if status == "warn" else "\u2b1c")
            desc = getattr(step, "description", "")
            label = f"{icon} {i:2d}. {step.name}"
            if desc:
                label += f"  ({desc})"
            choices.append(questionary.Choice(label, value=step))

        pending_count = sum(1 for _, s in statuses if s == "pending")
        choices.append(questionary.Choice(
            f">>> Run all pending ({pending_count} steps)", value="run_all",
        ))
        choices.append(questionary.Choice(">>> Exit", value="exit"))

        console.print()
        selected = questionary.select(
            "Select step (or run all):", choices=choices,
        ).ask()

        if selected is None or selected == "exit":
            break
        elif selected == "run_all":
            pending = [s for s, st in statuses if st != "ok"]
            if pending:
                run_steps(pending, console)
            else:
                console.print("[green]All steps already configured![/]")
        else:
            _run_single_step(selected, console, force_run=True)

    # Final summary
    final: list[tuple[str, str]] = []
    for step in steps:
        try:
            ok = step.check()
        except Exception:
            ok = False
        if not ok:
            final.append((step.name, "pending"))
            continue
        try:
            verified = step.verify()
        except Exception:
            verified = False
        final.append((step.name, "ok" if verified else "warn"))
    _print_summary(final, console)
    return all(s in {"ok", "warn"} for _, s in final)


def run_noninteractive(
    steps: Sequence[SetupStep],
    console: Console,
    *,
    check_only: bool = False,
) -> list[tuple[str, str]]:
    """Execute steps non-interactively (no prompts, no questionary).

    Returns list of (step_name, status) where status is
    "ok" | "failed" | "unavailable".
    """
    results: list[tuple[str, str]] = []

    for step in steps:
        try:
            ok = step.check()
        except Exception:
            ok = False

        if ok:
            console.print(f"  [green]\u2705 {step.name}[/] \u2014 already configured")
            results.append((step.name, "ok"))
            continue

        if check_only:
            console.print(f"  [dim]\u2b1c {step.name}[/] \u2014 unavailable")
            results.append((step.name, "unavailable"))
            continue

        # Attempt install + verify
        try:
            success = step.install(console)
        except Exception:
            success = False

        if success and step.verify():
            console.print(f"  [green]\u2705 {step.name}[/] \u2014 verified!")
            results.append((step.name, "ok"))
        else:
            console.print(f"  [red]\u274c {step.name}[/] \u2014 failed")
            results.append((step.name, "failed"))

    return results


def _print_summary(results: list[tuple[str, str]], console: Console) -> None:
    from rich.table import Table

    table = Table(title="Setup Summary", show_lines=False)
    table.add_column("Step", style="bold")
    table.add_column("Status")

    status_map = {
        "ok": "[green]\u2705 OK[/]",
        "skipped": "[yellow]\u23ed\ufe0f  Skipped[/]",
        "failed": "[red]\u274c Failed[/]",
        "warn": "[yellow]\u26a0\ufe0f  Warning[/]",
        "pending": "[dim]\u2b1c Pending[/]",
        "unavailable": "[dim]\u2b1c Unavailable[/]",
        "abort": "[red]\u274c Aborted[/]",
    }
    for name, status in results:
        table.add_row(name, status_map.get(status, status))

    console.print(table)
