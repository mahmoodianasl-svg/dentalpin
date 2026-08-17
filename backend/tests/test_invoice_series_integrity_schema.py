"""W0.3 default invoice-series PostgreSQL catalog contract."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

pytestmark = pytest.mark.schema_parity


@pytest.mark.asyncio
async def test_default_invoice_series_index_is_unique_and_partial() -> None:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT i.indisunique,
                                   pg_get_indexdef(i.indexrelid) AS definition,
                                   pg_get_expr(i.indpred, i.indrelid) AS predicate
                              FROM pg_index i
                              JOIN pg_class idx ON idx.oid = i.indexrelid
                             WHERE idx.relname = 'uq_invoice_series_default_per_type'
                            """
                        )
                    )
                )
                .mappings()
                .one()
            )
    finally:
        await engine.dispose()

    assert row["indisunique"] is True
    assert "(clinic_id, series_type)" in row["definition"]
    assert "is_default IS TRUE" in row["predicate"]
