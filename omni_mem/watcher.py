"""Automatic observation-count based synchronization."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

from .config import Config, load_watch_state, save_watch_state
from .sync import SyncEngine
from .worker import observation_fingerprints


def pending_observations(current: set[str], seen: set[str]) -> int:
    return len(current - seen)


def watch(config: Config, log_path: str | None = None) -> None:
    if not config.auto_sync.enabled:
        raise RuntimeError("automatic sync is disabled in the Omni-mem configuration")
    engine = SyncEngine(config)
    state = load_watch_state()
    current = observation_fingerprints()
    if not state.get("initialized"):
        state = {"initialized": True, "seen_observations": sorted(current)}
        save_watch_state(state)
        print(f"watcher baseline initialized with {len(current)} observations", flush=True)

    print(
        "watching claude-mem: "
        f"push every {config.auto_sync.observations_per_push} new observation(s), "
        f"polling every {config.auto_sync.poll_interval_seconds:g}s",
        flush=True,
    )
    log_file = None
    if log_path:
        log_file = Path(log_path)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_file.open("a", buffering=1)
    try:
        if log_file is not None:
            with contextlib.redirect_stdout(log_file), contextlib.redirect_stderr(log_file):
                _watch_loop(config, engine, state)
        else:
            _watch_loop(config, engine, state)
    finally:
        if log_file is not None:
            log_file.close()


def _watch_loop(config: Config, engine: SyncEngine, state: dict) -> None:
    try:
        while True:
            seen = set(state.get("seen_observations", []))
            current = observation_fingerprints()
            new_count = pending_observations(current, seen)
            if new_count >= config.auto_sync.observations_per_push:
                print(
                    f"{new_count} new observation(s) detected; "
                    f"waiting {config.auto_sync.debounce_seconds:g}s before push",
                    flush=True,
                )
                time.sleep(config.auto_sync.debounce_seconds)
                try:
                    engine.push()
                    state = load_watch_state()
                    print("automatic push completed", flush=True)
                except Exception as exc:
                    print(f"automatic push failed; will retry: {exc}", flush=True)
            time.sleep(config.auto_sync.poll_interval_seconds)
    except KeyboardInterrupt:
        print("watcher stopped", flush=True)
