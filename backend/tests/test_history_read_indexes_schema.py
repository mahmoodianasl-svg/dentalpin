"""W0.3 tenant-scoped history-read PostgreSQL index contract."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

if os.getenv("MIGRATED_SCHEMA_PARITY") != "true":
    pytest.skip("requires an Alembic-migrated schema", allow_module_level=True)

pytestmark = pytest.mark.schema_parity

EXPECTED_INDEXES = {
    "idx_invoice_history_clinic_invoice_changed": (
        "invoice_history",
        ["clinic_id", "invoice_id", "changed_at"],
    ),
    "idx_invoice_series_history_clinic_series_changed": (
        "invoice_series_history",
        ["clinic_id", "series_id", "changed_at"],
    ),
    "idx_budget_history_clinic_budget_changed": (
        "budget_history",
        ["clinic_id", "budget_id", "changed_at"],
    ),
    "ix_recall_attempts_clinic_recall_attempted": (
        "recall_contact_attempts",
        ["clinic_id", "recall_id", "attempted_at"],
    ),
}


@pytest.mark.asyncio
async def test_history_read_indexes_cover_tenant_parent_and_time() -> None:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT index_class.relname AS index_name,
                                   table_class.relname AS table_name,
                                   index_row.indisunique,
                                   index_row.indisvalid,
                                   array_agg(attribute.attname ORDER BY key.ordinality)
                                       AS columns
                              FROM pg_index index_row
                              JOIN pg_class index_class
                                ON index_class.oid = index_row.indexrelid
                              JOIN pg_class table_class
                                ON table_class.oid = index_row.indrelid
                              CROSS JOIN LATERAL
                                   unnest(index_row.indkey)
                                   WITH ORDINALITY AS key(attnum, ordinality)
                              JOIN pg_attribute attribute
                                ON attribute.attrelid = index_row.indrelid
                               AND attribute.attnum = key.attnum
                             WHERE index_class.relname IN (
                                   'idx_invoice_history_clinic_invoice_changed',
                                   'idx_invoice_series_history_clinic_series_changed',
                                   'idx_budget_history_clinic_budget_changed',
                                   'ix_recall_attempts_clinic_recall_attempted'
                               )
                             GROUP BY index_class.relname,
                                      table_class.relname,
                                      index_row.indisunique,
                                      index_row.indisvalid
                             ORDER BY index_class.relname
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
    finally:
        await engine.dispose()

    installed = {row["index_name"]: (row["table_name"], list(row["columns"])) for row in rows}
    assert installed == EXPECTED_INDEXES
    assert all(row["indisvalid"] is True for row in rows)
    assert all(row["indisunique"] is False for row in rows)
