"""Round-trip migration and irreversibility-policy tests.

Asserts that the head schema is reproducible — i.e. ``upgrade heads``
produces the same set of tables and columns whether you arrive there
from a clean DB or after a downgrade/reset.

The strict form is ``upgrade → downgrade base → upgrade``. We keep it
when every migration has a working ``downgrade``. When the graph contains
an explicitly one-way migration, descending past that wall is unsupported;
CI therefore verifies clean rebuild determinism and separately asserts that
every source-level ``NotImplementedError`` downgrade is present in the
reviewed one-way inventory below.

Production policy for one-way migrations is forward-fix plus tested database
backup/restore; W0.2 verifies that path in the schema-parity workflow.
"""

from __future__ import annotations

import ast
import asyncio
import subprocess
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest

from app.config import settings

pytestmark = pytest.mark.alembic_roundtrip

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

# Reviewed revisions whose downgrade is intentionally unsupported because the
# upgrade moves/de-duplicates data into a new ownership model. This set is a
# safety contract, not a convenience switch: ``test_one_way_revision_inventory``
# discovers every migration that raises NotImplementedError and requires exact
# equality with this inventory.
ONE_WAY_REVISIONS: frozenset[str] = frozenset(
    {
        # cn_0002: moves clinical_note_attachments into polymorphic
        # media_attachments and creates additional provenance links.
        "cn_0002",
        # tp_0004: consolidates treatment_media into media.media_attachments.
        "tp_0004",
    }
)


def _alembic(*args: str) -> None:
    """Run ``alembic <args>`` from the backend package root."""
    subprocess.run(
        ["alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=BACKEND_ROOT,
        check=True,
    )


def _migration_files() -> Iterator[Path]:
    """Yield every main and per-module migration revision file."""
    yield from sorted((BACKEND_ROOT / "alembic" / "versions").glob("*.py"))
    yield from sorted((BACKEND_ROOT / "app" / "modules").glob("*/migrations/versions/*.py"))


def _revision_and_one_way(path: Path) -> tuple[str | None, bool]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    revision: str | None = None

    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "revision" and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    revision = node.value.value
        elif isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "revision" for target in node.targets):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    revision = node.value.value

    one_way = any(
        isinstance(node, ast.Raise)
        and (
            isinstance(node.exc, ast.Name)
            and node.exc.id == "NotImplementedError"
            or isinstance(node.exc, ast.Call)
            and isinstance(node.exc.func, ast.Name)
            and node.exc.func.id == "NotImplementedError"
        )
        for node in ast.walk(tree)
    )
    return revision, one_way


def test_one_way_revision_inventory_is_complete() -> None:
    """Every intentionally irreversible revision must be explicitly reviewed."""
    discovered: set[str] = set()
    for path in _migration_files():
        revision, one_way = _revision_and_one_way(path)
        if one_way:
            assert revision, f"one-way migration has no revision id: {path}"
            discovered.add(revision)

    assert discovered == set(ONE_WAY_REVISIONS), (
        "Irreversible migration inventory drift. "
        f"source={sorted(discovered)}, reviewed={sorted(ONE_WAY_REVISIONS)}"
    )


def _asyncpg_dsn() -> str:
    """Strip ``postgresql+asyncpg://`` → ``postgresql://`` for asyncpg."""
    return settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


async def _snapshot_tables_async() -> dict[str, list[str]]:
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        tables = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name != 'alembic_version' "
            "ORDER BY table_name"
        )
        result: dict[str, list[str]] = {}
        for row in tables:
            tbl = row["table_name"]
            cols = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = $1 "
                "ORDER BY ordinal_position",
                tbl,
            )
            result[tbl] = [c["column_name"] for c in cols]
        return result
    finally:
        await conn.close()


def _snapshot_tables() -> dict[str, list[str]]:
    return asyncio.run(_snapshot_tables_async())


def _leftover_tables() -> list[str]:
    return list(_snapshot_tables().keys())


async def _drop_public_schema_async() -> None:
    """Drop every non-system table in public, including alembic_version."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        for row in rows:
            await conn.execute(f'DROP TABLE IF EXISTS "{row["tablename"]}" CASCADE')
    finally:
        await conn.close()


def _drop_public_schema() -> None:
    asyncio.run(_drop_public_schema_async())


def test_upgrade_downgrade_upgrade_is_schema_stable() -> None:
    """upgrade → reset → upgrade must produce the same schema.

    A strict downgrade-to-base is executed only when the reviewed graph has no
    one-way walls. When walls exist, backup/restore is the supported production
    recovery mechanism and this test retains clean-rebuild determinism.
    """
    _alembic("upgrade", "heads")
    before = _snapshot_tables()
    assert before, "expected at least one table after upgrade heads"

    if ONE_WAY_REVISIONS:
        _drop_public_schema()
        _alembic("stamp", "base")
        leftover = _leftover_tables()
        assert leftover == [], f"drop_public_schema left tables behind: {leftover}"
    else:
        _alembic("downgrade", "base")
        leftover = _leftover_tables()
        assert leftover == [], f"downgrade base left tables behind: {leftover}"

    _alembic("upgrade", "heads")
    after = _snapshot_tables()

    assert before == after, (
        "Schema drift after upgrade → reset → upgrade\n"
        f"before tables: {sorted(before)}\n"
        f"after tables:  {sorted(after)}"
    )
