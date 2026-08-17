#!/usr/bin/env python3
"""Generate frontend/modules.json using host-resolvable Nuxt layer paths."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES_DIR = ROOT / "backend" / "app" / "modules"
OUTPUT = ROOT / "frontend" / "modules.json"

entries: list[dict[str, str]] = []
for module_dir in sorted(MODULES_DIR.iterdir()):
    layer = module_dir / "frontend"
    if layer.is_dir():
        entries.append({"name": module_dir.name, "path": str(layer.resolve())})

payload = {
    "layers": [entry["path"] for entry in entries],
    "modules": entries,
    "version": 1,
}
OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {OUTPUT} with {len(entries)} Nuxt module layers")
