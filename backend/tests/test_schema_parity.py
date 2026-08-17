"""W0.2 migrated-schema parity checks.

This test intentionally runs against a database that CI has already migrated
with ``alembic upgrade heads``. It compares that production-shaped schema with
the complete SQLAlchemy metadata contract. Any autogenerate operation means
models and migrations disagree and W0.2 must remain red.
"""

from __future__ import annotations

from pprint import pformat

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.database import Base
from app.schema_registry import register_all_models

register_all_models()


def _collect_schema_diffs(connection: Connection) -> list[object]:
    context = MigrationContext.configure(
        connection,
        opts={
            "compare_type": True,
            "compare_server_default": True,
        },
    )
    return list(compare_metadata(context, Base.metadata))


@pytest.mark.asyncio
async def test_migrated_schema_matches_complete_metadata() -> None:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            diffs = await connection.run_sync(_collect_schema_diffs)
    finally:
        await engine.dispose()

    assert not diffs, "Migrated PostgreSQL schema differs from Base.metadata:\n" + pformat(
        diffs, width=120
    )
