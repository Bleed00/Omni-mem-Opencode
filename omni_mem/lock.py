"""A simple process lock based on atomic directory creation."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class SyncLock:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        try:
            self.path.mkdir(parents=True)
        except FileExistsError as exc:
            pid_path = self.path / "pid"
            try:
                pid = int(pid_path.read_text().strip())
            except (OSError, ValueError):
                pid = None
            if pid is not None and _process_is_alive(pid):
                raise RuntimeError(f"another Omni-mem operation is running: {self.path}") from exc
            shutil.rmtree(self.path, ignore_errors=True)
            self.path.mkdir(parents=True)
        (self.path / "pid").write_text(str(os.getpid()))
        return self

    def __exit__(self, exc_type, exc, traceback):
        shutil.rmtree(self.path, ignore_errors=True)


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
