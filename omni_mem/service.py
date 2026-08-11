"""Platform dispatcher for the automatic watcher service."""

from __future__ import annotations

import sys
from pathlib import Path

from .config import Config


def install(config: Config, launcher: Path | None) -> None:
    if sys.platform.startswith("win"):
        from .service_windows import install as _install
    else:
        from .service_linux import install as _install
    _install(config, launcher)


def remove() -> None:
    if sys.platform.startswith("win"):
        from .service_windows import remove as _remove
    else:
        from .service_linux import remove as _remove
    _remove()


def status() -> str:
    if sys.platform.startswith("win"):
        from .service_windows import status as _status
    else:
        from .service_linux import status as _status
    return _status()
