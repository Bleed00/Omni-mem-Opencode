"""Small, checked subprocess wrapper around the git CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def run(repo: Path, *args: str, check: bool = True) -> str:
    command = ["git", "-C", str(repo), *args]
    result = subprocess.run(command, text=True, capture_output=True)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitError(f"{' '.join(command)} failed: {detail}")
    return result.stdout.strip()


def remote_url(repo: Path) -> str:
    return run(repo, "remote", "get-url", "origin")


def is_dirty(repo: Path) -> bool:
    return bool(run(repo, "status", "--porcelain"))


def has_head(repo: Path) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
    ).returncode == 0


def clone(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "clone", url, str(destination)], text=True)
    if result.returncode != 0:
        raise GitError(f"failed to clone data repository: {url}")
