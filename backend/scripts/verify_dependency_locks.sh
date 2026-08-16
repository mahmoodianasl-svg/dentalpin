#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"
for lock in requirements.lock requirements-dev.lock; do
  if [[ ! -s "$lock" ]]; then
    echo "error: $lock is missing. Run scripts/compile_dependency_locks.sh in a connected environment." >&2
    exit 1
  fi
  grep -q -- '--hash=sha256:' "$lock" || { echo "error: $lock has no hashes" >&2; exit 1; }
done
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cp requirements.lock "$tmp/requirements.lock.expected"
cp requirements-dev.lock "$tmp/requirements-dev.lock.expected"
"$SCRIPT_DIR/compile_dependency_locks.sh"
cmp -s requirements.lock "$tmp/requirements.lock.expected" || { echo 'error: requirements.lock is stale' >&2; exit 1; }
cmp -s requirements-dev.lock "$tmp/requirements-dev.lock.expected" || { echo 'error: requirements-dev.lock is stale' >&2; exit 1; }
echo 'Backend dependency locks are current and reproducible.'
