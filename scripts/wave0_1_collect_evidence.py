#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("W0_EVIDENCE_DIR", ROOT / "artifacts" / "wave0_1"))
OUT.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd(*parts: str) -> str | None:
    try:
        return subprocess.check_output(parts, cwd=ROOT, text=True, stderr=subprocess.STDOUT).strip()
    except Exception:
        return None


def lock_version(name: str) -> str | None:
    p = ROOT / "frontend" / "package-lock.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    item = data.get("packages", {}).get(f"node_modules/{name}")
    return (item or {}).get("version")

files = [
    ".nvmrc",
    ".node-version",
    "backend/pyproject.toml",
    "backend/requirements.lock",
    "backend/requirements-dev.lock",
    "backend/dependency-lock-metadata.json",
    "frontend/package.json",
    "frontend/package-lock.json",
    "docs/portal/package-lock.json",
    "backend/Dockerfile",
    "frontend/Dockerfile.prod",
]

report = {
    "schema_version": 1,
    "wave": "W0.1",
    "commit": os.environ.get("GITHUB_SHA") or cmd("git", "rev-parse", "HEAD"),
    "runner": {
        "python": platform.python_version(),
        "node": cmd("node", "--version"),
        "npm": cmd("npm", "--version"),
        "uv": cmd("uv", "--version"),
        "docker": cmd("docker", "--version"),
    },
    "frontend_resolved": {
        "nuxt": lock_version("nuxt"),
        "@nuxt/devtools": lock_version("@nuxt/devtools"),
        "vite": lock_version("vite"),
        "@types/node": lock_version("@types/node"),
        "@nuxtjs/i18n": lock_version("@nuxtjs/i18n"),
        "@nuxt/test-utils": lock_version("@nuxt/test-utils"),
        "vitest": lock_version("vitest"),
    },
    "sha256": {rel: sha256(ROOT / rel) for rel in files},
    "git_diff_name_status": cmd("git", "diff", "--name-status"),
    "git_diff_stat": cmd("git", "diff", "--stat"),
}

(OUT / "w0_1_runtime_lock_evidence.json").write_text(json.dumps(report, indent=2) + "\n")
print(OUT / "w0_1_runtime_lock_evidence.json")
