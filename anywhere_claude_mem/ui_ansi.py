"""Zero-dependency ANSI terminal UI (Linux and other non-Windows platforms).

Mirrors the rich-based Windows backend (``ui_rich.py``) with plain ANSI escape
codes, box-drawing characters and a threaded spinner, so the CLI runs without
any pip package or virtual environment. Colors are disabled automatically when
the output is not a TTY or ``NO_COLOR`` is set.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from collections.abc import Callable, Iterable

from . import __version__

_RESET = "\x1b[0m"
_STYLES = {"green": "32", "red": "31", "yellow": "33", "cyan": "36", "dim": "2", "bold": "1"}
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_color_enabled_ = None


def reset_cache() -> None:
    global _color_enabled_
    _color_enabled_ = None


def _color_enabled() -> bool:
    global _color_enabled_
    if _color_enabled_ is None:
        _color_enabled_ = (
            sys.stdout.isatty()
            and os.environ.get("NO_COLOR") is None
            and os.environ.get("TERM") != "dumb"
        )
    return _color_enabled_


def _style(text: str, *styles: str) -> str:
    if not _color_enabled():
        return text
    codes = ";".join(_STYLES[name] for name in styles if name in _STYLES)
    return f"\x1b[{codes}m{text}{_RESET}" if codes else text


def _width(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _box(title: str, lines: Iterable[str], color: str = "green") -> str:
    rows = list(lines)
    inner = max([_width(line) for line in rows] + [0]) + 4
    out = []
    if title:
        title_text = _style(title, color, "bold")
        inner = max(inner, _width(title_text) + 4)
        sides = inner - _width(title_text) - 2
        left = sides // 2
        right = sides - left
        out.append(_style("╭" + "─" * left + " " + title_text + " " + "─" * right + "╮", color))
    else:
        out.append(_style("╭" + "─" * inner + "╮", color))
    for line in rows:
        pad = inner - 4 - _width(line)
        out.append(f"│  {line}" + " " * max(pad, 0) + "  │")
    out.append(_style("╰" + "─" * inner + "╯", color))
    return "\n".join(out)


# --- output ---------------------------------------------------------


def banner() -> None:
    title = f"anywhere-claude-mem v{__version__}"
    subtitle = "Synchronize claude-mem memory across OpenCode installs"
    print(_box(title, [subtitle], color="cyan"), flush=True)


def section(title: str) -> None:
    width = 60
    text = _style(title, "bold")
    sides = max(width - _width(text), 8)
    left = sides // 2
    right = sides - left
    print(flush=True)
    print(_style("─" * left + " " + text + " " + "─" * right, "cyan"), flush=True)
    print(flush=True)


def ok(label: str, detail: str = "") -> None:
    _line(label, "✓", "green", detail)


def fail(label: str, detail: str = "") -> None:
    _line(label, "✗", "red", detail)


def warn(label: str, detail: str = "") -> None:
    _line(label, "⚠", "yellow", detail)


def _line(label: str, glyph: str, color: str, detail: str) -> None:
    text = f"{_style(glyph, color)} {label}"
    if detail:
        text += f"  {_style(detail, 'dim')}"
    print(text, flush=True)


def note(message: str) -> None:
    print(_style(message, "dim"), flush=True)


def error(message: str) -> None:
    print(_box("Error", [message], color="red"), flush=True)


def summary(title: str, items: Iterable[tuple[str, str]]) -> None:
    lines = [f"{_style(key, 'cyan')}  {value}" for key, value in items]
    print(_box(title, lines, color="green"), flush=True)


# --- spinner ------------------------------------------------------------


def spinner(label: str, func: Callable, *args, **kwargs):
    if not _color_enabled():
        print(f"{label}...", flush=True)
        return func(*args, **kwargs)

    stop = threading.Event()

    def _animate() -> None:
        index = 0
        while not stop.is_set():
            frame = _style(_SPINNER_FRAMES[index % len(_SPINNER_FRAMES)], "cyan")
            sys.stdout.write(f"\r{frame} {label}...")
            sys.stdout.flush()
            index += 1
            stop.wait(0.1)
        sys.stdout.write("\r" + " " * (_width(label) + 8) + "\r")
        sys.stdout.flush()

    thread = threading.Thread(target=_animate, daemon=True)
    thread.start()
    success = False
    try:
        result = func(*args, **kwargs)
        success = True
        return result
    finally:
        stop.set()
        thread.join()
        glyph = _style("✓", "green") if success else _style("✗", "red")
        print(f"{glyph} {label}", flush=True)


# --- prompts -------------------------------------------------------------


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


def _read_key() -> str:
    """Read a single key in raw mode (arrow keys, Enter, y/n)."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        char = os.read(fd, 1)
        if char in (b"\x03", b"\x04"):
            raise SystemExit(1)
        if char in (b"\r", b"\n"):
            return "\n"
        if char == b"\x1b":
            sequence = os.read(fd, 2)
            return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(
                sequence.decode("utf-8", errors="replace"), "esc"
            )
        return char.decode("utf-8", errors="replace")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def ask_confirm(message: str, default: bool = False) -> bool:
    suffix = "[Y/n] " if default else "[y/N] "
    prompt = f"{_style('?', 'cyan')} {message} {_style(suffix, 'dim')}"
    if _is_interactive():
        while True:
            print(prompt, end="", flush=True)
            key = _read_key()
            print(flush=True)
            if key in {"y", "Y"}:
                return True
            if key in {"n", "N"}:
                return False
            if key == "\n":
                return default
    while True:
        value = input(prompt).strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def ask_text(message: str, default: str = "", validate: Callable | None = None) -> str:
    while True:
        value = input(f"{_style('?', 'cyan')} {message} ").strip() or default
        if validate is None:
            return value
        result = validate(value)
        if result is True:
            return value
        print(_style(result if isinstance(result, str) else "Invalid value.", "red"))


def ask_int(message: str, default: int) -> int:
    return int(ask_text(message, default=str(default), validate=_positive_int))


def ask_float(message: str, default: float) -> float:
    return float(ask_text(message, default=str(default), validate=_positive_float))


def ask_select(message: str, choices: list[str], default: str | None = None) -> str:
    if _is_interactive():
        selected = choices.index(default) if default in choices else 0
        first = True
        while True:
            if not first:
                sys.stdout.write(f"\x1b[{len(choices) + 1}A")
            first = False
            print(f"{_style('?', 'cyan')} {message}", flush=True)
            for index, choice in enumerate(choices):
                marker = _style("›", "cyan") if index == selected else " "
                print(f"  {marker} {choice}", flush=True)
            key = _read_key()
            if key == "up":
                selected = (selected - 1) % len(choices)
            elif key == "down":
                selected = (selected + 1) % len(choices)
            elif key == "\n":
                sys.stdout.write(f"\x1b[{len(choices) + 1}A")
                print(f"{_style('?', 'cyan')} {message}", flush=True)
                print(f"  {_style('✓', 'green')} {choices[selected]}", flush=True)
                return choices[selected]
    print(message)
    for index, choice in enumerate(choices, start=1):
        marker = f"  [{index}] {choice}"
        if choice == default:
            marker += "  (default)"
        print(marker, flush=True)
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
