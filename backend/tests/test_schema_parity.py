"""W0.2 migrated-schema parity checks.

This test intentionally runs against a database that CI has already migrated
with ``alembic upgrade heads``. It compares that production-shaped schema with
the complete SQLAlchemy migration metadata contract.

W0.2 is repaired in two explicit stages. This structural gate compares tables,
columns/types, foreign keys, unique/check constraints and indexes first. Server
default parity is intentionally handled as a separate follow-up contract so
large historical default differences cannot obscure higher-risk structural
schema drift.
"""

from __future__ import annotations

from collections import Counter
from pprint import pformat
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import MetaData

from app.config import settings
from app.schema_registry import build_migration_metadata


def _operation_name(diff: Any) -> str:
    """Return a compact operation name for an Alembic comparison diff."""
    current = diff
    while isinstance(current, list) and current:
        current = current[0]
    if isinstance(current, tuple) and current:
        return str(current[0])
    return type(current).__name__


def _format_diffs(diffs: list[object]) -> str:
    counts = Counter(_operation_name(diff) for diff in diffs)
    summary = ", ".join(f"{name}={counts[name]}" for name in sorted(counts))
    return f"Structural drift summary: {summary}\n\n{pformat(diffs, width=120)}"


def _collect_schema_diffs(connection: Connection, metadata: MetaData) -> list[object]:
    context = MigrationContext.configure(
        connection,
        opts={
            "compare_type": True,
            # Server defaults are normalized in the second W0.2 stage. Keep
            # this first gate focused on structural production-schema parity.
            "compare_server_default": False,
        },
    )
    return list(compare_metadata(context, metadata))


@pytest.mark.asyncio
async def test_migrated_schema_matches_complete_metadata() -> None:
    # Build a private migration metadata view for this comparison. This must
    # never mutate global Base.metadata because the ordinary backend test suite
    # deliberately exercises existing ORM/create_all helper behavior too.
    migration_metadata = build_migration_metadata()

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            diffs = await connection.run_sync(
                lambda sync_connection: _collect_schema_diffs(sync_connection, migration_metadata)
            )
    finally:
        await engine.dispose()

    assert not diffs, (
        "Migrated PostgreSQL schema differs from migration metadata:\n" + _format_diffs(diffs)
    )
