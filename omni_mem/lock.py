"""A simple process lock based on atomic directory creation."""

from __future__ import annotations

import os
import shutil
import sys
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
    if sys.platform.startswith("win"):
        return _windows_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_is_alive(pid: int) -> bool:
    """Check a Windows process without os.kill (which is not supported on Windows)."""
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)
