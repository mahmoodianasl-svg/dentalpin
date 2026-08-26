#!/usr/bin/env python3
"""Fail when DentalPin release version metadata drifts."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_VERSION = re.compile(r"^## \[(?P<version>[^]]+)]", re.MULTILINE)


def application_version() -> str:
    """Read VERSION without importing the application dependency graph."""
    tree = ast.parse((ROOT / "backend/app/version.py").read_text())
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "VERSION"
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    raise ValueError("backend/app/version.py must assign VERSION to a string literal")


def versions() -> dict[str, str]:
    """Return every independently persisted release version."""
    backend = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())
    frontend = json.loads((ROOT / "frontend/package.json").read_text())
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    changelog = CHANGELOG_VERSION.search((ROOT / "CHANGELOG.md").read_text())
    if changelog is None:
        raise ValueError("CHANGELOG.md has no version heading")

    return {
        "application": application_version(),
        "backend package": backend["project"]["version"],
        "frontend package": frontend["version"],
        "frontend lockfile": lock["version"],
        "frontend lockfile root": lock["packages"][""]["version"],
        "changelog": changelog.group("version"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--expected", help="Expected version derived from the release tag"
    )
    args = parser.parse_args()

    found = versions()
    expected = args.expected or next(iter(found.values()))
    drift = {
        source: version for source, version in found.items() if version != expected
    }
    if drift:
        details = ", ".join(f"{source}={version}" for source, version in drift.items())
        raise SystemExit(f"release metadata must equal {expected}: {details}")

    print(f"release metadata is consistent at {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
