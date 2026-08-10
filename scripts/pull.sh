#!/usr/bin/env bash
# pull.sh - downloads from the DATA REPO and imports the memory into the local
# worker.
#
# The data repo is the git clone in $DATA_DIR (data/ folder inside the wrapper).
#
# What it does:
#   1. git pull (safety stash for uncommitted local changes)
#   2. import $DATA_DIR/*.json into the worker (idempotent, dedup by id)
set -euo pipefail

source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib.sh"

base="$(require_worker)"

if [ ! -d "$DATA_DIR/.git" ]; then
  echo "ERROR: the data repo is not cloned at ${DATA_DIR}." >&2
  echo "  Run install.sh first: bash install.sh" >&2
  exit 1
fi
cd "$DATA_DIR"

stashed=0
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git branch -M main
  echo "Data repo has no local commits: pointing at branch main."
elif [ -n "$(git status --porcelain)" ]; then
  echo "uncommitted local changes found: temporary stash..."
  git stash push --include-untracked --quiet
  stashed=1
fi

echo "pulling from the remote..."
if ! git pull --rebase --quiet origin main; then
  [ "$stashed" -eq 1 ] && git stash pop --quiet 2>/dev/null || true
  echo "ERROR: git pull failed. See above." >&2
  exit 1
fi

if [ "$stashed" -eq 1 ]; then
  echo "restoring local changes..."
  git stash pop --quiet || true
fi

echo "importing memory into the worker (${base})..."
python3 "${REPO_ROOT}/scripts/import.py" "$base" "$DATA_DIR"
