#!/usr/bin/env python3
"""Export observations/summaries/prompts/sessions from the claude-mem worker into data/.

- observations/summaries/prompts: via the worker API (pagination of 100)
- sessions (sdk_sessions): via the local SQLite DB, read-only, to provide
  /api/import with the content_session_id -> memory_session_id mapping
  (required by summaries).
- Summaries are enriched with memory_session_id derived from that same mapping,
  otherwise the import would fail with a NOT NULL constraint.

Union-merge by id with the already-present content: remote entries that no
longer exist locally are preserved.
"""
import json
import os
import sqlite3
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:37700"
DATA_DIR = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data"
)

PAGE = 100
DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), ".claude-mem")


def settings():
    try:
        with open(os.path.join(DEFAULT_DATA_DIR, "settings.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def db_path():
    data_dir = settings().get("CLAUDE_MEM_DATA_DIR") or DEFAULT_DATA_DIR
    return os.path.join(data_dir, "claude-mem.db")


def fetch_all(endpoint):
    items = []
    offset = 0
    while True:
        url = f"{BASE}{endpoint}?limit={PAGE}&offset={offset}"
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
        chunk = data.get("items", [])
        items.extend(chunk)
        if not data.get("hasMore"):
            break
        offset += PAGE
    return items


def load_sessions_from_db():
    """Read sdk_sessions from the local DB (read-only)."""
    path = db_path()
    if not os.path.exists(path):
        print(f"sessions: DB not found ({path}), skipped")
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT content_session_id, memory_session_id, project, platform_source,"
            " user_prompt, started_at, started_at_epoch, completed_at,"
            " completed_at_epoch, status FROM sdk_sessions"
        ).fetchall()
        con.close()
    except Exception as e:
        print(f"sessions: failed to read DB: {e}")
        return []
    return [dict(r) for r in rows]


def session_mapping(sessions):
    m = {}
    for s in sessions:
        if s.get("content_session_id") and s.get("memory_session_id"):
            m[s["content_session_id"]] = s["memory_session_id"]
    return m


def merge_by_id(path, fetched):
    merged = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                for item in json.load(f):
                    if isinstance(item, dict) and "id" in item:
                        merged[item["id"]] = item
        except Exception:
            pass
    for item in fetched:
        if isinstance(item, dict) and "id" in item:
            merged[item["id"]] = item
    return sorted(merged.values(), key=lambda x: x.get("id", 0))


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    sessions = load_sessions_from_db()
    mapping = session_mapping(sessions)

    with open(os.path.join(DATA_DIR, "sessions.json"), "w") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)
    print(f"sessions: {len(sessions)} from local DB")

    summaries = fetch_all("/api/summaries")
    for s in summaries:
        if not s.get("memory_session_id") and s.get("session_id"):
            s["memory_session_id"] = mapping.get(s["session_id"])
    merged_sum = merge_by_id(os.path.join(DATA_DIR, "summaries.json"), summaries)
    with open(os.path.join(DATA_DIR, "summaries.json"), "w") as f:
        json.dump(merged_sum, f, indent=2, ensure_ascii=False)
    print(f"summaries: {len(summaries)} from worker, {len(merged_sum)} total in file")

    for name, endpoint in (
        ("observations", "/api/observations"),
        ("prompts", "/api/prompts"),
    ):
        fetched = fetch_all(endpoint)
        merged = merge_by_id(os.path.join(DATA_DIR, f"{name}.json"), fetched)
        with open(os.path.join(DATA_DIR, f"{name}.json"), "w") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        print(f"{name}: {len(fetched)} from worker, {len(merged)} total in file")


if __name__ == "__main__":
    main()
