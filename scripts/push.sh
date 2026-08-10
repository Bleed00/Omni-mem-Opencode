#!/usr/bin/env bash
# push.sh - exports the local memory from the worker and publishes it to the
# DATA REPO.
#
# The data repo is the git clone in $DATA_DIR (data/ folder inside the
# wrapper), which acts as storage and is separate from the wrapper repo.
#
# What it does:
#   1. export observations/summaries/prompts/sessions -> $DATA_DIR/*.json
#   2. commit local changes
#   3. pull --rebase from the remote (brings in changes from other PCs)
#   4. push
set -euo pipefail

source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib.sh"

base="$(require_worker)"

if [ ! -d "$DATA_DIR/.git" ]; then
  echo "ERROR: the data repo is not cloned at ${DATA_DIR}." >&2
  echo "  Run install.sh first: bash install.sh" >&2
  exit 1
fi
cd "$DATA_DIR"

first=""
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  first=1
  echo "Data repo has no local commits: first setup - pointing at branch main."
  git branch -M main
fi

echo "exporting memory from the worker (${base})..."
python3 "${REPO_ROOT}/scripts/export.py" "$base" "$DATA_DIR"

if [ -z "$(git status --porcelain -- '*.json')" ]; then
  echo "No changes in the memory to sync."
else
  git add -A -- '*.json'
  git commit -m "sync: export memory $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
fi

if [ -n "$first" ]; then
  git push --quiet --set-upstream origin main
  echo "Memory exported and pushed (first push)."
  exit 0
fi

echo "pulling from the remote..."
if ! git pull --rebase --quiet; then
  echo "ERROR: git pull failed. Resolve the conflicts and retry omni-push." >&2
  exit 1
fi

git push --quiet
echo "Memory exported and pushed."
