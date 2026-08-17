#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-}"
if [[ -z "$SRC" || ! -d "$SRC" ]]; then
  echo "usage: $0 <extracted-github-artifact-directory>" >&2
  exit 2
fi
for rel in \
  backend/requirements.lock \
  backend/requirements-dev.lock \
  backend/dependency-lock-metadata.json \
  frontend/package.json \
  frontend/package-lock.json; do
  if [[ ! -f "$SRC/$rel" ]]; then
    echo "error: artifact is missing $rel" >&2
    exit 2
  fi
  mkdir -p "$(dirname "$ROOT/$rel")"
  cp "$SRC/$rel" "$ROOT/$rel"
done
python3 "$ROOT/scripts/check_wave0_1_baseline.py" --strict
echo "Applied W0.1 generated locks. Review git diff, then run the normal CI matrix before marking W0.1 PASS."
