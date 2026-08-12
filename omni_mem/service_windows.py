"""Windows logon autostart for the automatic watcher.

Task Scheduler was the original mechanism, but on filtered (non-elevated)
accounts both Register-ScheduledTask and schtasks /Create are denied
("Accesso negato"), and a command line that embeds an %APPDATA% path is
rejected at CreateProcess by the reputation/AV layer. The per-user HKCU Run
key starts pythonw at logon without elevation, without schtasks and without
PowerShell, at the cost of no restart-on-crash (acceptable trade-off).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config import Config, config_dir

TASK_NAME = "omni-mem-watch"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

try:
    import winreg
except ImportError:  # pragma: no cover - Windows only; None keeps the module importable elsewhere
    winreg = None  # type: ignore[assignment]


def pythonw_path() -> str:
    """pythonw.exe runs with no console window; watch() prints become no-ops."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.is_file() else sys.executable


def run_command_line() -> str:
    """Command stored in the Run key; starts the watcher at logon."""
    exe = pythonw_path()
    log_path = config_dir() / "watch.log"
    return f'"{exe}" -m omni_mem watch --log "{log_path}"'


def _run_key(access: int):
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def install(config: Config, launcher: Path | None) -> None:
    with _run_key(winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, TASK_NAME, 0, winreg.REG_SZ, run_command_line())


def _creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def remove() -> None:
    try:
        with _run_key(winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, TASK_NAME)
    except FileNotFoundError:
        pass
    # Clean up a scheduled task registered by earlier versions.
    subprocess.run(
        f'schtasks /Delete /TN "{TASK_NAME}" /F',
        shell=False,
        check=False,
        capture_output=True,
        creationflags=_creationflags(),
    )


def status() -> str:
    try:
        with _run_key(winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, TASK_NAME)
        return "enabled"
    except FileNotFoundError:
        return "inactive"
