"""Linux systemd user-service integration."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import Config


SERVICE_NAME = "omni-mem-watch.service"
LEGACY_TIMER = "omni-mem-push.timer"
LEGACY_SERVICE = "omni-mem-push.service"


def unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def unit_path() -> Path:
    return unit_dir() / SERVICE_NAME


def install(config: Config, launcher: Path) -> None:
    if shutil.which("systemctl") is None:
        raise RuntimeError("systemctl was not found; automatic sync requires systemd on Linux")
    unit_dir().mkdir(parents=True, exist_ok=True)
    unit_path().write_text(
        "[Unit]\n"
        "Description=Omni-mem automatic claude-mem synchronization\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={launcher} watch\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", SERVICE_NAME], check=True)


def remove() -> None:
    if shutil.which("systemctl"):
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", SERVICE_NAME],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", LEGACY_TIMER],
            check=False,
            capture_output=True,
        )
    unit_path().unlink(missing_ok=True)
    (unit_dir() / LEGACY_SERVICE).unlink(missing_ok=True)
    (unit_dir() / LEGACY_TIMER).unlink(missing_ok=True)
    if shutil.which("systemctl"):
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"], check=False, capture_output=True
        )


def status() -> str:
    if shutil.which("systemctl") is None:
        return "systemd unavailable"
    result = subprocess.run(
        ["systemctl", "--user", "is-active", SERVICE_NAME], text=True, capture_output=True
    )
    return result.stdout.strip() or "inactive"
