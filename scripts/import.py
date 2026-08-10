#!/usr/bin/env python3
"""Import observations/summaries/prompts from data/ into the claude-mem worker.

Idempotent: /api/import dedups by id, so re-running does not create duplicates.
"""
import json
import os
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:37700"
DATA_DIR = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data"
)


def load(name):
    path = os.path.join(DATA_DIR, f"{name}.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def main():
    payload = {
        "sessions": load("sessions"),
        "observations": load("observations"),
        "summaries": load("summaries"),
        "prompts": load("prompts"),
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}/api/import", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.load(r)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
