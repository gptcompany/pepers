"""Cascading step runner for setup wizards."""

from __future__ import annotations

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


def _run_single_step(step: SetupStep, console: Console) -> str:
    """Execute check -> install -> verify for a single step.

    Returns status: "ok" | "skipped" | "failed" | "warn" | "abort".
    """
    with console.status(f"[bold cyan]Checking {step.name}...[/]"):
        if step.check():
            console.print(f"  [green]\u2705 {step.name}[/] \u2014 already configured")
            return "ok"

    if not questionary.confirm(
        f"Configure {step.name}?", default=True
    ).ask():
        console.print(f"  [yellow]\u23ed\ufe0f  {step.name}[/] \u2014 skipped")
        return "skipped"

    success = step.install(console)
    if not success:
        action = questionary.select(
            f"{step.name} failed. What to do?",
            choices=["Skip and continue", "Retry", "Abort"],
        ).ask()
        if action == "Abort":
            console.print("[bold red]Setup aborted.[/]")
            return "abort"
        if action == "Retry":
            success = step.install(console)
            if not success:
                console.print(
                    f"  [red]\u274c {step.name}[/] \u2014 retry failed, skipping"
                )
                return "failed"
        else:
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
            statuses.append((step, "ok" if ok else "pending"))

        # Build menu choices
        choices: list[questionary.Choice] = []
        for i, (step, status) in enumerate(statuses, 1):
            icon = "\u2705" if status == "ok" else "\u2b1c"
            desc = getattr(step, "description", "")
            label = f"{icon} {i:2d}. {step.name}"
            if desc:
                label += f"  ({desc})"
            choices.append(questionary.Choice(label, value=step))

        pending_count = sum(1 for _, s in statuses if s != "ok")
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
            _run_single_step(selected, console)

    # Final summary
    final: list[tuple[str, str]] = []
    for step in steps:
        try:
            ok = step.check()
        except Exception:
            ok = False
        final.append((step.name, "ok" if ok else "pending"))
    _print_summary(final, console)
    return all(s == "ok" for _, s in final)


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
        "abort": "[red]\u274c Aborted[/]",
    }
    for name, status in results:
        table.add_row(name, status_map.get(status, status))

    console.print(table)
