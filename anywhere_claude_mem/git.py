"""Small, checked subprocess wrapper around the git CLI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def creationflags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def run(repo: Path, *args: str, check: bool = True) -> str:
    command = ["git", "-C", str(repo), *args]
    result = subprocess.run(command, text=True, capture_output=True, creationflags=creationflags())
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitError(f"{' '.join(command)} failed: {detail}")
    return result.stdout.strip()


def remote_url(repo: Path) -> str:
    return run(repo, "remote", "get-url", "origin")


def is_dirty(repo: Path) -> bool:
    return bool(run(repo, "status", "--porcelain"))


def cleanup_temp_artifacts(repo: Path) -> int:
    """Delete stray temp/backup files left in the data directory by interrupted writes.

    ``data.write_records`` (and friends) create ``NamedTemporaryFile`` files directly
    inside the data directory and rename them into place. If a write is interrupted
    between creation and rename, a ``tmpXXXXXXXX`` (or a stray ``*.bak``) file is left
    behind. Hundreds of those make ``git stash push --include-untracked`` build a huge
    index and can fail on Windows with ``could not write index``. We always scrub them
    before any git operation that stashes untracked files.

    Returns the number of artifacts removed.
    """
    removed = 0
    for pattern in ("tmp*", "*.bak", "*.tmp"):
        for match in repo.glob(pattern):
            if match.is_file():
                try:
                    match.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


def dirty_json(repo: Path) -> bool:
    """True when the working tree has real changes to tracked *.json files.

    Unlike :func:`is_dirty`, this ignores stray untracked artifacts (``tmp*``,
    ``*.bak``) that carry no sync data. Used before stashing so we only stash when
    there is actual JSON data to protect.
    """
    try:
        lines = run(repo, "status", "--porcelain")
    except GitError:
        return False
    for line in lines.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # index/working-tree codes: XY path
        status_code = stripped[:2]
        path = stripped[3:].strip()
        if status_code in ("??", "!!"):
            # untracked/ignored: only relevant if it looks like a data json our
            # push/import cares about (the tracked *.json are handled below on the
            # M/A/D cases). tmp*/bak only clutter the index, so ignore them.
            if not (path.endswith(".json") and "tmp" not in path.lower() and ".bak" not in path.lower()):
                continue
        if path.endswith(".json"):
            return True
    return False


def unmerged_paths(repo: Path) -> bool:
    """True when a rebase/merge is mid-flight with unresolved conflicts."""
    try:
        return "UU" in run(repo, "status", "--porcelain")
    except GitError:
        return False


def has_head(repo: Path) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        creationflags=creationflags(),
    ).returncode == 0


def ref(repo: Path, name: str) -> str:
    return run(repo, "rev-parse", name)


def clone(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", url, str(destination)],
        text=True,
        creationflags=creationflags(),
    )
    if result.returncode != 0:
        raise GitError(f"failed to clone data repository: {url}")
