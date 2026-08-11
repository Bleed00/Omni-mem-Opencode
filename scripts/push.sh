#!/usr/bin/env bash
# Compatibility wrapper. The implementation lives in the Python CLI.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
cd "$ROOT"
exec python3 -m omni_mem push "$@"
