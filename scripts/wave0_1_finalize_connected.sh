#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_NODE="24.19.0"
ACTUAL_NODE="$(node --version 2>/dev/null | sed 's/^v//' || true)"
if [[ "$ACTUAL_NODE" != "$EXPECTED_NODE" ]]; then
  echo "error: Node $EXPECTED_NODE required; found ${ACTUAL_NODE:-none}. Use .nvmrc/.node-version." >&2
  exit 2
fi
NPM_MAJOR="$(npm --version | cut -d. -f1)"
if [[ "$NPM_MAJOR" != "11" ]]; then
  echo "error: npm 11 is required with the pinned Node baseline; found $(npm --version)." >&2
  exit 2
fi
if ! command -v python3.11 >/dev/null 2>&1 || [[ "$(python3.11 -c 'import platform; print(platform.python_version())')" != "3.11.15" ]]; then
  echo "error: Python 3.11.15 must be available as python3.11." >&2
  exit 2
fi
if ! command -v uv >/dev/null 2>&1 || [[ "$(uv --version | awk '{print $2}')" != "0.12.1" ]]; then
  echo "error: uv 0.12.1 is required for the reviewed W0.1 baseline." >&2
  exit 2
fi

# W0.1 dependency locks are finalized and reviewed. This verification path is
# deliberately read-only: it must never regenerate package-lock.json or Python
# lock files, because registry resolution can drift even with pinned toolchains.
cd "$ROOT"
python3 scripts/check_wave0_1_baseline.py --strict

cd "$ROOT/frontend"
npm ci --no-audit --no-fund

cd "$ROOT/docs/portal"
npm ci --no-audit --no-fund

cd "$ROOT"
python3 scripts/check_wave0_1_baseline.py --strict

echo 'Wave 0.1 dependency baseline verified without lock regeneration.'
