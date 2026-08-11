"""Synchronization engine shared by the CLI and the watcher."""

from __future__ import annotations

from . import data, git
from .config import Config, load_watch_state, save_watch_state, state_path
from .lock import SyncLock
from .worker import WorkerClient, observation_fingerprints


class SyncEngine:
    def __init__(self, config: Config):
        self.config = config
        self.data_dir = config.data_path
        self.lock_path = state_path().with_name("operation.lock")

    def ensure_data_repo(self) -> None:
        if not (self.data_dir / ".git").is_dir():
            raise RuntimeError(
                f"data repository is not cloned at {self.data_dir}. Run 'omni-mem install' first."
            )

    def push(self) -> dict[str, int]:
        self.ensure_data_repo()
        worker = WorkerClient()
        worker.check()
        with SyncLock(self.lock_path):
            counts = data.export_snapshot(worker, self.data_dir)
            if git.is_dirty(self.data_dir):
                git.run(self.data_dir, "add", "-A", "--", "*.json")
                git.run(self.data_dir, "commit", "-m", "sync: export memory")
            if not git.has_head(self.data_dir):
                git.run(self.data_dir, "branch", "-M", "main")
                git.run(self.data_dir, "push", "--set-upstream", "origin", "main")
            else:
                git.run(self.data_dir, "pull", "--rebase", "--quiet")
                git.run(self.data_dir, "push", "--quiet")
            mark_observations_seen()
            return counts

    def pull(self) -> dict:
        self.ensure_data_repo()
        worker = WorkerClient()
        worker.check()
        with SyncLock(self.lock_path):
            stashed = False
            if git.has_head(self.data_dir) and git.is_dirty(self.data_dir):
                git.run(self.data_dir, "stash", "push", "--include-untracked", "--quiet")
                stashed = True
            try:
                if git.has_head(self.data_dir):
                    git.run(self.data_dir, "pull", "--rebase", "--quiet", "origin", "main")
            finally:
                if stashed:
                    git.run(self.data_dir, "stash", "pop", "--quiet")
            result = data.import_snapshot(worker, self.data_dir)
            mark_observations_seen()
            return result


def mark_observations_seen() -> None:
    state = load_watch_state()
    state["initialized"] = True
    state["seen_observations"] = sorted(observation_fingerprints())
    save_watch_state(state)


def status(config: Config) -> dict:
    try:
        WorkerClient().check()
        worker_ok = True
    except Exception:
        worker_ok = False
    repo_ok = (config.data_path / ".git").is_dir()
    remote = ""
    if repo_ok:
        try:
            remote = git.remote_url(config.data_path)
        except Exception:
            pass
    return {
        "worker": worker_ok,
        "data_repo": repo_ok,
        "data_repo_dir": str(config.data_path),
        "data_repo_url": remote or config.data_repo_url,
        "auto_sync": config.auto_sync.__dict__,
        "state_file": str(state_path()),
    }
