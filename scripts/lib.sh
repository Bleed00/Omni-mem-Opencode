#!/usr/bin/env bash
# Shared helpers for the Omni-mem-Opencode sync commands.
#
# The data/ folder inside the wrapper is the LOCAL CLONE of the data repo on
# GitHub (which acts as storage). The push/pull scripts operate on that clone.

set -euo pipefail

# Real path of the wrapper (follows symlinks in ~/.local/bin).
resolve_repo_root() {
  local self
  self="$(readlink -f "${BASH_SOURCE[0]}")"
  dirname "$(dirname "$self")"
}

REPO_ROOT="$(resolve_repo_root)"
DATA_DIR="${REPO_ROOT}/data"

# claude-mem worker port: CLAUDE_MEM_WORKER_PORT from settings.json,
# otherwise the default 37700 + (uid % 100).
worker_port() {
  local port
  port="$(
    python3 - <<'PY'
import json, os
try:
    with open(os.path.expanduser("~/.claude-mem/settings.json")) as f:
        s = json.load(f)
    print(s.get("CLAUDE_MEM_WORKER_PORT") or "")
except Exception:
    print("")
PY
  )"
  if [ -n "$port" ]; then
    printf '%s' "$port"
    return
  fi
  python3 - <<'PY'
import os
uid = os.getuid() if hasattr(os, "getuid") else 77
print(37700 + (uid % 100))
PY
}

worker_base() {
  printf 'http://127.0.0.1:%s' "$(worker_port)"
}

# Check that the worker is reachable; print the base URL on stdout.
require_worker() {
  local base
  base="$(worker_base)"
  if ! curl -s --max-time 5 "${base}/api/health" >/dev/null 2>&1; then
    echo "ERROR: claude-mem worker unreachable at ${base}" >&2
    echo "  Start opencode (which starts the worker) or run: npx claude-mem start" >&2
    return 1
  fi
  printf '%s' "$base"
}
