"""Portable JSON export/import and stable cross-device record keys."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from .worker import WorkerClient, load_sessions


def stable_key(kind: str, item: dict) -> str:
    if kind == "sessions":
        return "\0".join(
            [str(item.get("platform_source", "claude")), str(item.get("content_session_id", ""))]
        )
    if kind == "observations":
        return "\0".join(
            [
                str(item.get("memory_session_id", "")),
                str(item.get("title", "")),
                str(item.get("created_at_epoch", "")),
            ]
        )
    if kind == "summaries":
        return str(item.get("memory_session_id") or item.get("session_id") or item.get("id"))
    if kind == "prompts":
        return "\0".join(
            [
                str(item.get("platform_source", "claude")),
                str(item.get("content_session_id", "")),
                str(item.get("prompt_number", "")),
            ]
        )
    raise ValueError(f"unknown record kind: {kind}")


def read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as stream:
        data = json.load(stream)
    return data if isinstance(data, list) else []


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    with NamedTemporaryFile("w", dir=path.parent, delete=False) as temp:
        temp.write(content)
        temp_path = Path(temp.name)
    temp_path.replace(path)


def merge_records(data_dir: Path, kind: str, fetched: list[dict]) -> list[dict]:
    path = data_dir / f"{kind}.json"
    merged = {stable_key(kind, item): item for item in read_records(path)}
    merged.update({stable_key(kind, item): item for item in fetched})
    return sorted(merged.values(), key=lambda item: stable_key(kind, item))


def add_placeholder_sessions(sessions: list[dict], records: list[dict]) -> list[dict]:
    """Create importable session rows for legacy observations without a session.

    Older exports can contain observations whose original SDK session was
    already cleaned up locally. The observations table has a foreign key, so
    importing those records requires a minimal completed session row first.
    """
    known = {item.get("memory_session_id") for item in sessions}
    placeholders = []
    for item in records:
        memory_id = item.get("memory_session_id")
        if not memory_id or memory_id in known:
            continue
        timestamp = item.get("created_at_epoch") or 0
        placeholders.append(
            {
                "content_session_id": memory_id,
                "memory_session_id": memory_id,
                "project": item.get("project") or "unknown",
                "platform_source": item.get("platform_source") or "claude",
                "user_prompt": None,
                "started_at": item.get("created_at"),
                "started_at_epoch": timestamp,
                "completed_at": item.get("created_at"),
                "completed_at_epoch": timestamp,
                "status": "completed",
            }
        )
        known.add(memory_id)
    return sessions + placeholders


def export_snapshot(worker: WorkerClient, data_dir: Path) -> dict[str, int]:
    data_dir.mkdir(parents=True, exist_ok=True)
    sessions = load_sessions()
    summaries = worker.fetch_all("/api/summaries")
    observations = worker.fetch_all("/api/observations")
    prompts = worker.fetch_all("/api/prompts")

    existing_observations = read_records(data_dir / "observations.json")
    all_observations = merge_records(data_dir, "observations", observations)
    sessions = add_placeholder_sessions(sessions, existing_observations + all_observations)
    merged_sessions = merge_records(data_dir, "sessions", sessions)
    mapping = {
        item["content_session_id"]: item["memory_session_id"]
        for item in merged_sessions
        if item.get("content_session_id") and item.get("memory_session_id")
    }
    for summary in summaries:
        if not summary.get("memory_session_id"):
            summary["memory_session_id"] = mapping.get(summary.get("session_id")) or summary.get(
                "session_id"
            )
    summaries = merge_records(data_dir, "summaries", summaries)
    prompts = merge_records(data_dir, "prompts", prompts)
    records = {
        "sessions": merged_sessions,
        "summaries": summaries,
        "observations": all_observations,
        "prompts": prompts,
    }
    for kind, items in records.items():
        write_records(data_dir / f"{kind}.json", items)
    return {kind: len(items) for kind, items in records.items()}


def import_snapshot(worker: WorkerClient, data_dir: Path) -> dict:
    payload = {kind: read_records(data_dir / f"{kind}.json") for kind in (
        "sessions", "observations", "summaries", "prompts"
    )}
    return worker.import_data(payload)
