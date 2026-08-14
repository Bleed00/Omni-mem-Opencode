"""rich/questionary terminal UI (Windows).

The Windows package is installed with ``pip install -e .`` which also installs
these dependencies. Every helper degrades to plain text when ``rich`` is not
available.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from . import __version__

_console = None
_MARKUP_TAG = re.compile(r"\[/?[^\]]*\]")


def reset_cache() -> None:
    """Forget the cached rich console (used after bootstrapping dependencies)."""
    global _console
    _console = None


def _get_console():
    global _console
    if _console is None:
        try:
            from rich.console import Console

            _console = Console()
        except ImportError:
            _console = False
    return _console or None


def _print_line(text: str) -> None:
    console = _get_console()
    if console is None:
        print(_MARKUP_TAG.sub("", text), flush=True)
    else:
        console.print(text)


# --- output ---------------------------------------------------------


def banner() -> None:
    console = _get_console()
    title = f"anywhere-claude-mem v{__version__}"
    subtitle = "Synchronize claude-mem memory across OpenCode installs"
    if console is None:
        print(title)
        print(subtitle)
        print("-" * 40)
        return
    from rich.panel import Panel

    console.print(
        Panel(
            f"[bold cyan]{title}[/bold cyan]\n[dim]{subtitle}[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


def section(title: str) -> None:
    console = _get_console()
    if console is None:
        print()
        print(f"== {title} ==")
        print()
        return
    console.rule(f"[bold]{title}[/bold]")


def ok(label: str, detail: str = "") -> None:
    text = f"[green]\u2713[/green] {label}"
    if detail:
        text += f"  [dim]{detail}[/dim]"
    _print_line(text)


def fail(label: str, detail: str = "") -> None:
    text = f"[red]\u2717[/red] {label}"
    if detail:
        text += f"  [dim]{detail}[/dim]"
    _print_line(text)


def warn(label: str, detail: str = "") -> None:
    text = f"[yellow]\u26a0[/yellow] {label}"
    if detail:
        text += f"  [dim]{detail}[/dim]"
    _print_line(text)


def note(message: str) -> None:
    console = _get_console()
    if console is None:
        _print_line(message)
        return
    console.print(f"[dim]{message}[/dim]")


def error(message: str) -> None:
    console = _get_console()
    if console is None:
        _print_line(f"ERROR: {message}")
        return
    from rich.panel import Panel

    console.print(Panel.fit(f"[bold red]{message}[/bold red]", title="Error", border_style="red"))


def summary(title: str, items: Iterable[tuple[str, str]]) -> None:
    console = _get_console()
    if console is None:
        print()
        print(f"== {title} ==")
        for key, value in items:
            print(f"  {key}: {value}")
        print()
        return
    from rich.panel import Panel
    from rich.table import Table

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="bold cyan")
    table.add_column()
    for key, value in items:
        table.add_row(key, value)
    console.print(Panel(table, title=title, border_style="green"))


# --- spinner ---------------------------------------------------------


def spinner(label: str, func: Callable, *args, **kwargs):
    """Run ``func`` while showing a spinner under ``label``."""
    console = _get_console()
    if console is None:
        _print_line(f"{label}...")
        return func(*args, **kwargs)
    with console.status(f"[bold cyan]{label}...[/bold cyan]"):
        return func(*args, **kwargs)


# --- prompts ------------------------------------------------------------


def _asked(value):
    if value is None:  # prompt aborted (Ctrl+C)
        raise SystemExit(1)
    return value


def _positive_int(value: str):
    try:
        return int(value) > 0 or "Please enter a positive integer."
    except ValueError:
        return "Please enter a positive integer."


def _positive_float(value: str):
    try:
        return float(value) > 0 or "Please enter a positive number."
    except ValueError:
        return "Please enter a positive number."


def ask_confirm(message: str, default: bool = False) -> bool:
    try:
        import questionary

        return bool(_asked(questionary.confirm(message, default=default).ask()))
    except ImportError:
        return _fallback_confirm(message, default)


def _fallback_confirm(message: str, default: bool) -> bool:
    suffix = "[Y/n] " if default else "[y/N] "
    while True:
        value = input(f"{message} {suffix}").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def ask_text(message: str, default: str = "", validate: Callable | None = None) -> str:
    try:
        import questionary

        return _asked(questionary.text(message, default=default, validate=validate).ask())
    except ImportError:
        return _fallback_text(message, default, validate)


def _fallback_text(message: str, default: str, validate: Callable | None) -> str:
    while True:
        value = input(f"{message} ").strip() or default
        if validate is None:
            return value
        result = validate(value)
        if result is True:
            return value
        print(result if isinstance(result, str) else "Invalid value.")


def ask_int(message: str, default: int) -> int:
    return int(ask_text(message, default=str(default), validate=_positive_int))


def ask_float(message: str, default: float) -> float:
    return float(ask_text(message, default=str(default), validate=_positive_float))


def ask_select(message: str, choices: list[str], default: str | None = None) -> str:
    try:
        import questionary

        return _asked(questionary.select(message, choices=choices, default=default).ask())
    except ImportError:
        return _fallback_select(message, choices, default)


def _fallback_select(message: str, choices: list[str], default: str | None) -> str:
    print(message)
    for index, choice in enumerate(choices, start=1):
        marker = f"  [{index}] {choice}"
        if choice == default:
            marker += "  (default)"
        _print_line(marker)
    while True:
        value = input("> ").strip()
        if not value and default:
            return default
        try:
            index = int(value)
            if 1 <= index <= len(choices):
                return choices[index - 1]
        except ValueError:
            pass
        for choice in choices:
            if value.lower() == choice.lower():
                return choice
        print("Please choose one of the options.")
