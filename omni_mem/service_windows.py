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
    try:
        _register_with_restart()
    except subprocess.CalledProcessError:
        # Register-ScheduledTask needs elevation on many setups (0x80070005,
        # "Access denied"). schtasks works unelevated for the current user but
        # cannot set restart-on-failure, so the watcher is restarted at logon.
        print(
            "Note: Register-ScheduledTask requires elevation; falling back to "
            "schtasks (the watcher runs at logon but does not auto-restart on crash).",
            flush=True,
        )
        _register_with_schtasks()


def _register_with_restart() -> None:
    """PowerShell registration with restart-on-failure settings (needs elevation)."""
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
        capture_output=True,
        text=True,
    )


def schtasks_command_line() -> str:
    """schtasks registration command line (works unelevated for the current user).

    /TR embeds the executable and arguments; inner quotes are escaped with
    backslashes as documented for schtasks /Create.
    """
    exe = pythonw_path()
    log_path = config_dir() / "watch.log"
    tr = f'"\\"{exe}\\" -m omni_mem watch --log \\"{log_path}\\""'
    return (
        f'schtasks /Create /TN "{TASK_NAME}" /TR {tr} '
        "/SC ONLOGON /RL LIMITED /F"
    )


def _register_with_schtasks() -> None:
    result = subprocess.run(
        schtasks_command_line(),
        shell=False,
        text=True,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"failed to register scheduled task: {result.stderr.strip() or result.stdout.strip()}"
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
    subprocess.run(
        f'schtasks /Delete /TN "{TASK_NAME}" /F',
        shell=False,
        check=False,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
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
    state = result.stdout.strip()
    if state:
        return state
    query = subprocess.run(
        f'schtasks /Query /TN "{TASK_NAME}"',
        shell=False,
        text=True,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "inactive" if query.returncode != 0 else "Ready"
