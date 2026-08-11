"""Local claude-mem worker and SQLite access."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.request
from pathlib import Path


DEFAULT_PORT = 37700


def settings_path() -> Path:
    return Path.home() / ".claude-mem" / "settings.json"


def settings() -> dict:
    try:
        with settings_path().open() as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError):
        return {}


def worker_port() -> int:
    configured = os.environ.get("CLAUDE_MEM_WORKER_PORT") or settings().get("CLAUDE_MEM_WORKER_PORT")
    if configured:
        return int(configured)
    uid = os.getuid() if hasattr(os, "getuid") else 77
    return DEFAULT_PORT + (uid % 100)


def database_path() -> Path:
    data_dir = settings().get("CLAUDE_MEM_DATA_DIR") or str(Path.home() / ".claude-mem")
    return Path(data_dir).expanduser() / "claude-mem.db"


class WorkerClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or f"http://127.0.0.1:{worker_port()}"

    def request(self, path: str, method: str = "GET", payload: dict | None = None) -> dict:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=headers, method=method
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)

    def check(self) -> None:
        self.request("/api/health")

    def fetch_all(self, endpoint: str) -> list[dict]:
        items: list[dict] = []
        offset = 0
        while True:
            result = self.request(f"{endpoint}?limit=100&offset={offset}")
            chunk = result.get("items", [])
            items.extend(chunk)
            if not result.get("hasMore"):
                return items
            offset += 100

    def import_data(self, payload: dict) -> dict:
        return self.request("/api/import", method="POST", payload=payload)


def load_sessions() -> list[dict]:
    path = database_path()
    if not path.exists():
        return []
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT content_session_id, memory_session_id, project, platform_source,"
            " user_prompt, started_at, started_at_epoch, completed_at,"
            " completed_at_epoch, status FROM sdk_sessions"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def observation_fingerprints() -> set[str]:
    path = database_path()
    if not path.exists():
        return set()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT memory_session_id, title, created_at_epoch FROM observations"
        ).fetchall()
        return {observation_fingerprint(row[0], row[1], row[2]) for row in rows}
    finally:
        connection.close()


def observation_fingerprint(memory_session_id: str, title: str | None, created_at_epoch: int) -> str:
    value = json.dumps(
        [memory_session_id, title or "", created_at_epoch], separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(value.encode()).hexdigest()
