"""Local claude-mem worker and SQLite access."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.request
import urllib.error
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


def worker_data_dir() -> Path:
    data_dir = settings().get("CLAUDE_MEM_DATA_DIR") or str(Path.home() / ".claude-mem")
    return Path(data_dir).expanduser()


def _port_from_worker_files() -> int | None:
    """The worker records its active port in worker.pid / supervisor.json.

    On Windows there is no uid, so the DEFAULT_PORT + uid%100 formula cannot be
    trusted; the recorded port is authoritative. Also checked on POSIX first,
    falling back to the uid formula only if nothing usable is found.
    """
    data_dir = worker_data_dir()
    for name in ("worker.pid", "supervisor.json"):
        path = data_dir / name
        if not path.exists():
            continue
        try:
            with path.open() as stream:
                raw = json.load(stream)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        for key in ("port", "workerPort"):
            value = raw.get(key)
            if isinstance(value, int) and value > 0:
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    return None


def _probe_health_port() -> int | None:
    for port in range(DEFAULT_PORT, DEFAULT_PORT + 100):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=0.3
            ) as response:
                if response.status == 200:
                    return port
        except Exception:
            continue
    return None


def worker_port() -> int:
    configured = os.environ.get("CLAUDE_MEM_WORKER_PORT") or settings().get("CLAUDE_MEM_WORKER_PORT")
    if configured:
        return int(configured)
    recorded = _port_from_worker_files()
    if recorded:
        return recorded
    probed = _probe_health_port()
    if probed:
        return probed
    if hasattr(os, "getuid"):
        uid = os.getuid()
        return DEFAULT_PORT + (uid % 100)
    return DEFAULT_PORT


def database_path() -> Path:
    return worker_data_dir() / "claude-mem.db"


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
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace").strip()
            except OSError:
                detail = ""
            message = f"worker returned HTTP {exc.code}"
            if detail:
                message += f": {detail}"
            raise RuntimeError(message) from exc

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

    def delete(self, kind: str, record_id: int) -> bool:
        """Delete a single record through the worker API.

        Returns False when the record no longer exists (already gone).
        """
        endpoint = {"observations": "observation", "summaries": "summary", "prompts": "prompt"}.get(kind)
        if endpoint is None:
            raise ValueError(f"no worker delete endpoint for kind: {kind}")
        try:
            self.request(f"/api/{endpoint}/{record_id}", method="DELETE")
            return True
        except RuntimeError as exc:
            if "404" in str(exc):
                return False
            raise


def delete_local_sessions(memory_session_ids: list[str]) -> int:
    """Delete SDK session rows directly, cascading to their records."""
    if not memory_session_ids:
        return 0
    path = database_path()
    if not path.exists():
        return 0
    connection = sqlite3.connect(str(path), timeout=30)
    try:
        cursor = connection.executemany(
            "DELETE FROM sdk_sessions WHERE memory_session_id = ?",
            [(memory_id,) for memory_id in memory_session_ids],
        )
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()


def _connect_read_only(path: Path) -> sqlite3.Connection:
    """Open the claude-mem database without risking writes.

    A `file:...?mode=ro` URI can break on Windows paths and against WAL
    databases, so connect normally and enforce read-only per-connection.
    """
    connection = sqlite3.connect(str(path), timeout=30)
    connection.execute("PRAGMA query_only = ON")
    return connection


def load_sessions() -> list[dict]:
    path = database_path()
    if not path.exists():
        return []
    connection = _connect_read_only(path)
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
    connection = _connect_read_only(path)
    try:
        rows = connection.execute(
            "SELECT title, created_at_epoch FROM observations"
        ).fetchall()
        return {observation_fingerprint(row[0], row[1]) for row in rows}
    finally:
        connection.close()


def observation_fingerprint(title: str | None, created_at_epoch: int) -> str:
    value = json.dumps(
        [title or "", created_at_epoch], separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(value.encode()).hexdigest()
