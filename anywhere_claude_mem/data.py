"""Portable JSON export/import and stable cross-device record keys."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from .config import get_last_exported, set_last_exported
from .worker import WorkerClient, delete_local_sessions, load_sessions


def stable_key(kind: str, item: dict) -> str:
    if kind == "sessions":
        return "\0".join(
            [str(item.get("platform_source", "claude")), str(item.get("content_session_id", ""))]
        )
    if kind == "observations":
        return "\0".join(
            [
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


TOMBSTONE_FILE = "tombstones.json"

OBSERVATION_CONTENT_FIELDS = [
    "memory_session_id", "project", "type", "title", "subtitle", "text",
    "facts", "narrative", "concepts", "files_read", "files_modified",
    "prompt_number", "discovery_tokens", "created_at", "created_at_epoch",
]

SESSION_CONTENT_FIELDS = [
    "content_session_id", "memory_session_id", "project", "platform_source",
    "user_prompt", "started_at", "started_at_epoch", "completed_at",
    "completed_at_epoch", "status",
]

SUMMARY_CONTENT_FIELDS = [
    "memory_session_id", "project", "request", "investigated", "learned",
    "completed", "next_steps", "files_read", "files_edited", "notes",
    "prompt_number", "discovery_tokens", "created_at", "created_at_epoch",
]

PROMPT_CONTENT_FIELDS = [
    "content_session_id", "prompt_number", "prompt_text", "created_at",
    "created_at_epoch",
]

CONTENT_FIELDS = {
    "observations": OBSERVATION_CONTENT_FIELDS,
    "sessions": SESSION_CONTENT_FIELDS,
    "summaries": SUMMARY_CONTENT_FIELDS,
    "prompts": PROMPT_CONTENT_FIELDS,
}


def record_signature(kind: str, item: dict) -> str:
    """Canonical hash of the user-meaningful content of a record.

    Ignores bookkeeping fields (id, content_hash, sync metadata) so identical
    content produces the same signature regardless of where it was imported.
    memory_session_id is device-specific (regenerated on each machine), so it
    is excluded too: the same conversation must hash identically everywhere.
    """
    fields = [
        name for name in CONTENT_FIELDS[kind]
        if name != "memory_session_id" and name in item
    ]
    value = json.dumps(
        {name: item[name] for name in fields},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str,
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _empty_tombstones() -> dict[str, set[str]]:
    return {kind: set() for kind in CONTENT_FIELDS}


def read_tombstones(data_dir: Path) -> dict[str, set[str]]:
    path = data_dir / TOMBSTONE_FILE
    if not path.exists():
        return _empty_tombstones()
    try:
        with path.open() as stream:
            raw = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return _empty_tombstones()
    return {kind: set(raw.get(kind, [])) for kind in CONTENT_FIELDS}


def write_tombstones(data_dir: Path, tombstones: dict[str, set[str]]) -> None:
    payload = {kind: sorted(keys) for kind, keys in tombstones.items()}
    data_dir.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=data_dir, delete=False) as temp:
        json.dump(payload, temp, indent=2, ensure_ascii=False)
        temp.write("\n")
        temp_path = Path(temp.name)
    temp_path.replace(data_dir / TOMBSTONE_FILE)


def merge_tombstones(a: dict[str, set[str]], b: dict[str, set[str]]) -> dict[str, set[str]]:
    return {kind: set(a.get(kind, set())) | set(b.get(kind, set())) for kind in CONTENT_FIELDS}


def prune_tombstoned(kind: str, records: list[dict], tombstones: dict[str, set[str]]) -> list[dict]:
    keys = tombstones.get(kind, set())
    if not keys:
        return records
    return [item for item in records if stable_key(kind, item) not in keys]


def collect_local_records(worker: WorkerClient) -> dict[str, list[dict]]:
    """Records currently in the local DB, with numeric ids for the API deletes."""
    return {
        "sessions": load_sessions(),
        "observations": worker.fetch_all("/api/observations"),
        "summaries": worker.fetch_all("/api/summaries"),
        "prompts": worker.fetch_all("/api/prompts"),
    }


def _deletion_fields(kind: str, payload_record: dict) -> list[str]:
    return [
        name for name in CONTENT_FIELDS[kind]
        if name != "memory_session_id" and name in payload_record
    ]


def plan_deletions(
    payload: dict[str, list[dict]],
    local: dict[str, list[dict]],
    tombstones: dict[str, set[str]],
) -> dict[str, list]:
    """Local record ids to delete before importing a snapshot.

    Deletes a local record when its stable key is tombstoned (deletion
    propagated from another machine) or when the payload holds a different
    version of the same key (modification; the record is re-inserted during
    import).  Sessions are returned by memory_session_id for the SQL delete.
    """
    plan: dict[str, list] = {"sessions": [], "observations": [], "summaries": [], "prompts": []}
    for kind in ("observations", "summaries", "prompts"):
        local_by_key: dict[str, list[dict]] = {}
        for rec in local.get(kind, []):
            local_by_key.setdefault(stable_key(kind, rec), []).append(rec)
        payload_by_key = {stable_key(kind, rec): rec for rec in payload.get(kind, [])}
        for key, lrecs in local_by_key.items():
            if key in tombstones.get(kind, set()):
                plan[kind].extend(rec["id"] for rec in lrecs if rec.get("id") is not None)
            elif key in payload_by_key:
                fields = _deletion_fields(kind, payload_by_key[key])
                psig = record_signature(kind, payload_by_key[key])
                if any(record_signature(kind, rec) != psig for rec in lrecs):
                    plan[kind].extend(rec["id"] for rec in lrecs if rec.get("id") is not None)
    # sessions: no numeric id from load_sessions, use memory_session_id
    local_by_key = {}
    for rec in local.get("sessions", []):
        local_by_key.setdefault(stable_key("sessions", rec), []).append(rec)
    payload_sessions = {stable_key("sessions", rec): rec for rec in payload.get("sessions", [])}
    for key, lrecs in local_by_key.items():
        if key in tombstones.get("sessions", set()):
            plan["sessions"].extend(
                rec["memory_session_id"] for rec in lrecs if rec.get("memory_session_id")
            )
        elif key in payload_sessions:
            psig = record_signature("sessions", payload_sessions[key])
            if any(record_signature("sessions", rec) != psig for rec in lrecs):
                plan["sessions"].extend(
                    rec["memory_session_id"] for rec in lrecs if rec.get("memory_session_id")
                )
    return plan


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
    sessions_raw = load_sessions()
    summaries = worker.fetch_all("/api/summaries")
    observations = worker.fetch_all("/api/observations")
    prompts = worker.fetch_all("/api/prompts")

    existing_observations = read_records(data_dir / "observations.json")
    all_observations = merge_records(data_dir, "observations", observations)
    sessions = add_placeholder_sessions(sessions_raw, existing_observations + all_observations)
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
    merged_summaries = merge_records(data_dir, "summaries", summaries)
    merged_prompts = merge_records(data_dir, "prompts", prompts)

    # detect local deletions: keys this machine exported before but no longer has
    tombstones = read_tombstones(data_dir)
    last = get_last_exported()
    local_keys = {
        "sessions": {stable_key("sessions", s) for s in sessions},
        "observations": {stable_key("observations", o) for o in observations},
        "summaries": {stable_key("summaries", s) for s in summaries},
        "prompts": {stable_key("prompts", p) for p in prompts},
    }
    for kind in local_keys:
        deleted = set(last.get(kind, [])) - local_keys[kind]
        tombstones[kind] |= deleted

    merged_sessions = prune_tombstoned("sessions", merged_sessions, tombstones)
    all_observations = prune_tombstoned("observations", all_observations, tombstones)
    merged_summaries = prune_tombstoned("summaries", merged_summaries, tombstones)
    merged_prompts = prune_tombstoned("prompts", merged_prompts, tombstones)

    records = {
        "sessions": merged_sessions,
        "summaries": merged_summaries,
        "observations": all_observations,
        "prompts": merged_prompts,
    }
    for kind, items in records.items():
        write_records(data_dir / f"{kind}.json", items)
    write_tombstones(data_dir, tombstones)

    set_last_exported({kind: sorted(keys) for kind, keys in local_keys.items()})
    return {kind: len(items) for kind, items in records.items()}


def reconcile_sessions_with_db(payload: dict) -> dict:
    """Align payload session ids with the local database before importing.

    The worker dedupes sessions by (platform_source, content_session_id), but
    sdk_sessions.memory_session_id is UNIQUE and referenced by observations and
    summaries. When the payload carries a stale memory id for a session the
    local database already knows under a different id, the worker skips the
    session and the subsequent FK insert of its observations fails. Rewrite the
    payload so every memory_session_id matches what the local database expects,
    and drop payload sessions that would collide on the UNIQUE memory id.
    """
    local = load_sessions()
    db_by_content = {
        (row.get("platform_source") or "claude", row.get("content_session_id")): row.get(
            "memory_session_id"
        )
        for row in local
    }
    db_by_memory = {row.get("memory_session_id") for row in local}

    sessions = payload.get("sessions") or []
    renamed: dict[str, str] = {}
    kept: list[dict] = []
    # Memory ids already claimed locally, or already adopted into the kept payload.
    # This also dedupes payload sessions that share a memory_session_id among
    # themselves (e.g. a real row plus its add_placeholder_sessions twin), which is
    # the shape a first import can receive: the UNIQUE constraint on
    # sdk_sessions.memory_session_id would otherwise be violated on the second row.
    claimed_mids = set(db_by_memory)
    for session in sessions:
        content = session.get("content_session_id")
        if not content:
            continue
        key = (session.get("platform_source") or "claude", content)
        mid = session.get("memory_session_id")
        local_id = db_by_content.get(key)
        if local_id:
            if mid and mid != local_id:
                renamed[mid] = local_id
                session["memory_session_id"] = local_id
            elif not mid:
                session["memory_session_id"] = local_id
            kept.append(session)
        elif mid in claimed_mids:
            # This memory id is already claimed by another content session (either
            # already in the local DB, or already kept from this same payload);
            # importing the row would violate the UNIQUE index.
            renamed[mid] = mid
        else:
            kept.append(session)
        if session.get("memory_session_id"):
            claimed_mids.add(session["memory_session_id"])
    payload["sessions"] = kept

    for kind in ("observations", "summaries"):
        for item in payload.get(kind) or []:
            mid = item.get("memory_session_id")
            if mid in renamed:
                item["memory_session_id"] = renamed[mid]
    return payload


def import_snapshot(worker: WorkerClient, data_dir: Path) -> dict:
    payload = {kind: read_records(data_dir / f"{kind}.json") for kind in (
        "sessions", "observations", "summaries", "prompts"
    )}
    tombstones = read_tombstones(data_dir)

    # delete local records that were deleted or modified on another machine
    local = collect_local_records(worker)
    plan = plan_deletions(payload, local, tombstones)
    for kind, by_id in (("observations", "id"), ("summaries", "id"), ("prompts", "id")):
        for record_id in plan[kind]:
            worker.delete(kind, record_id)
    if plan["sessions"]:
        delete_local_sessions(plan["sessions"])

    # prune tombstoned records so they are not re-imported as new
    for kind in ("sessions", "observations", "summaries", "prompts"):
        payload[kind] = prune_tombstoned(kind, payload[kind], tombstones)

    payload = reconcile_sessions_with_db(payload)
    known = {row.get("memory_session_id") for row in load_sessions()}
    orphans = [
        item
        for item in (payload.get("observations") or []) + (payload.get("summaries") or [])
        if item.get("memory_session_id") and item["memory_session_id"] not in known
    ]
    payload["sessions"] = add_placeholder_sessions(payload.get("sessions") or [], orphans)
    result = worker.import_data(payload)

    # refresh last_exported to what this machine now holds, for future deletions
    current = collect_local_records(worker)
    set_last_exported(
        {kind: sorted({stable_key(kind, rec) for rec in current[kind]}) for kind in current}
    )
    return result
