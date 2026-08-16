#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"
UV_VERSION_REQUIRED="${UV_VERSION_REQUIRED:-0.12.1}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: Python 3.11.15 is required to generate the lock (set PYTHON_BIN if needed)." >&2
  exit 2
fi
PYTHON_VERSION_ACTUAL="$("$PYTHON_BIN" -c 'import platform; print(platform.python_version())')"
if [[ "$PYTHON_VERSION_ACTUAL" != "3.11.15" ]]; then
  echo "error: expected Python 3.11.15; found $PYTHON_VERSION_ACTUAL via $PYTHON_BIN." >&2
  exit 2
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is required (expected ${UV_VERSION_REQUIRED})." >&2
  exit 2
fi
UV_VERSION_ACTUAL="$(uv --version | awk '{print $2}')"
if [[ "${UV_VERSION_ACTUAL}" != "${UV_VERSION_REQUIRED}" ]]; then
  echo "error: expected uv ${UV_VERSION_REQUIRED}; found ${UV_VERSION_ACTUAL}." >&2
  echo "Set UV_VERSION_REQUIRED only as an explicit reviewed lock-generator upgrade." >&2
  exit 2
fi
COMMON=(--universal --python "$PYTHON_BIN" --resolution highest --prerelease disallow --generate-hashes)
uv pip compile pyproject.toml "${COMMON[@]}" --output-file requirements.lock
uv pip compile pyproject.toml --extra dev "${COMMON[@]}" --output-file requirements-dev.lock
grep -q -- '--hash=sha256:' requirements.lock
grep -q -- '--hash=sha256:' requirements-dev.lock
"$PYTHON_BIN" - "$UV_VERSION_ACTUAL" "$PYTHON_VERSION_ACTUAL" <<'EOF_LOCK_META'
import hashlib, json, pathlib, sys
root=pathlib.Path('.')
uv_version, python_version=sys.argv[1:3]
def sha(name): return hashlib.sha256((root/name).read_bytes()).hexdigest()
meta={
    'schema_version': 1,
    'generator': {'uv': uv_version, 'python': python_version},
    'pyproject_sha256': sha('pyproject.toml'),
    'requirements_lock_sha256': sha('requirements.lock'),
    'requirements_dev_lock_sha256': sha('requirements-dev.lock'),
}
(root/'dependency-lock-metadata.json').write_text(json.dumps(meta, indent=2)+'\n')
EOF_LOCK_META
echo "Generated backend/requirements.lock, requirements-dev.lock and dependency-lock-metadata.json with uv ${UV_VERSION_ACTUAL}."
