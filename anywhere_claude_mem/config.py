"""Configuration and local state for Anywhere-claude-mem."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile


APP_NAME = "anywhere-claude-mem"


def config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if base:
            return Path(base).expanduser() / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base).expanduser() / APP_NAME if base else Path.home() / ".config" / APP_NAME


def restrict_permissions(path: Path) -> None:
    """Restrict config file access; POSIX only (Windows uses ACLs, chmod makes files read-only)."""
    if os.name == "posix":
        path.chmod(0o600)


def config_path() -> Path:
    return config_dir() / "config.json"


def state_path() -> Path:
    return config_dir() / "watch-state.json"


@dataclass
class AutoSyncConfig:
    enabled: bool = False
    observations_per_push: int = 1
    poll_interval_seconds: float = 5.0
    debounce_seconds: float = 10.0


@dataclass
class StartupPullConfig:
    enabled: bool = True
    retry_attempts: int = 12
    retry_delay_seconds: float = 5.0


@dataclass
class Config:
    wrapper_dir: str
    data_repo_dir: str
    data_repo_url: str = ""
    auto_sync: AutoSyncConfig = field(default_factory=AutoSyncConfig)
    startup_pull: StartupPullConfig = field(default_factory=StartupPullConfig)
    platform: str = "opencode"
    dsh_profile: str = ""

    @property
    def wrapper_path(self) -> Path:
        return Path(self.wrapper_dir).expanduser().resolve()

    @property
    def data_path(self) -> Path:
        return Path(self.data_repo_dir).expanduser().resolve()


def save_config(config: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(config)
    with NamedTemporaryFile("w", dir=path.parent, delete=False) as temp:
        json.dump(payload, temp, indent=2)
        temp.write("\n")
        temp_path = Path(temp.name)
    temp_path.replace(path)
    restrict_permissions(path)


def load_config() -> Config:
    path = config_path()
    if not path.exists():
        raise RuntimeError(f"configuration not found: {path}. Run 'anywhere-claude-mem install' first.")
    with path.open() as stream:
        raw = json.load(stream)
    auto = AutoSyncConfig(**raw.get("auto_sync", {}))
    startup = StartupPullConfig(**raw.get("startup_pull", {}))
    platform = raw.get("platform", "opencode")
    if platform not in ("opencode", "deepseek"):
        platform = "opencode"
    return Config(
        wrapper_dir=raw["wrapper_dir"],
        data_repo_dir=raw["data_repo_dir"],
        data_repo_url=raw.get("data_repo_url", ""),
        auto_sync=auto,
        startup_pull=startup,
        platform=platform,
        dsh_profile=raw.get("dsh_profile", ""),
    )


def load_watch_state() -> dict:
    path = state_path()
    if not path.exists():
        return {"initialized": False, "seen_observations": []}
    try:
        with path.open() as stream:
            state = json.load(stream)
        state.setdefault("initialized", False)
        state.setdefault("seen_observations", [])
        return state
    except (OSError, json.JSONDecodeError):
        return {"initialized": False, "seen_observations": []}


def save_watch_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, delete=False) as temp:
        json.dump(state, temp, indent=2)
        temp.write("\n")
        temp_path = Path(temp.name)
    temp_path.replace(path)
    restrict_permissions(path)


def get_last_exported() -> dict[str, list[str]]:
    """Stable keys exported on the last push, per record kind.

    Used by the export to detect local deletions: a key present here but
    missing from the current snapshot was deleted and must be tombstoned.
    """
    return load_watch_state().get("last_exported", {})


def set_last_exported(keys_by_kind: dict[str, list[str]]) -> None:
    state = load_watch_state()
    state["last_exported"] = keys_by_kind
    save_watch_state(state)
