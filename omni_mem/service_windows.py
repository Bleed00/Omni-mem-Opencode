"""Windows Task Scheduler integration for the automatic watcher."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config import Config, config_dir

TASK_NAME = "omni-mem-watch"
DESCRIPTION = "Omni-mem automatic claude-mem synchronization"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def pythonw_path() -> str:
    """pythonw.exe runs with no console window; watch() prints become no-ops."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.is_file() else sys.executable


def install(config: Config, launcher: Path | None) -> None:
    log_path = config_dir() / "watch.log"
    exe = pythonw_path()
    argument = f'-m omni_mem watch --log "{log_path}"'
    script = (
        "$action = New-ScheduledTaskAction "
        f"-Execute {_ps_quote(exe)} "
        f"-Argument {_ps_quote(argument)};"
        "$trigger = New-ScheduledTaskTrigger -AtLogOn;"
        "$settings = New-ScheduledTaskSettingsSet "
        "-RestartCount 999 "
        "-RestartInterval (New-TimeSpan -Minutes 1) "
        "-ExecutionTimeLimit (New-TimeSpan -Seconds 0);"
        f"Register-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} "
        "-Action $action -Trigger $trigger -Settings $settings "
        f"-Description {_ps_quote(DESCRIPTION)} -Force;"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
    )


def remove() -> None:
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Unregister-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -Confirm:$false",
        ],
        check=False,
        capture_output=True,
    )


def status() -> str:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"$task = Get-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -ErrorAction SilentlyContinue; "
            "if ($task) { $task.State } else { 'inactive' }",
        ],
        text=True,
        capture_output=True,
    )
    return result.stdout.strip() or "inactive"
