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
  echo "error: Python 3.11.15 must be available as python3.11 before lock finalization." >&2
  exit 2
fi
python3 - "$ROOT/frontend/package.json" <<'EOF_NODE_PACKAGE'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text())
d['dependencies']['nuxt']='4.5.1'
d['dependencies']['@nuxtjs/i18n']='10.6.0'
d['devDependencies']['@types/node']='24.13.3'
d['devDependencies']['@nuxt/test-utils']='4.1.0'
d['devDependencies']['vitest']='4.1.10'
p.write_text(json.dumps(d, indent=2)+'\n')
EOF_NODE_PACKAGE
cd "$ROOT/frontend"
npm install --package-lock-only --ignore-scripts --no-audit --no-fund
npm update @nuxt/devtools vite --package-lock-only --ignore-scripts --no-audit --no-fund
npm ci --no-audit --no-fund
cd "$ROOT/docs/portal"
npm ci --no-audit --no-fund
cd "$ROOT/backend"
./scripts/compile_dependency_locks.sh
cd "$ROOT"
python3 scripts/check_wave0_1_baseline.py --strict
echo 'Wave 0.1 dependency baseline finalized. Run the full test matrix before marking the gate PASS.'
