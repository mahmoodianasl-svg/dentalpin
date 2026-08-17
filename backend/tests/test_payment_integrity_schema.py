"""W0.3 PostgreSQL payment-integrity catalog contract."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

pytestmark = pytest.mark.schema_parity

EXPECTED_TRIGGERS = {
    ("payments", "trg_payments_financial_integrity"),
    ("payment_allocations", "trg_payment_allocations_financial_integrity"),
    ("refunds", "trg_refunds_financial_integrity"),
}


@pytest.mark.asyncio
async def test_payment_integrity_triggers_are_deferred_constraints() -> None:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT c.relname AS table_name,
                               t.tgname AS trigger_name,
                               t.tgdeferrable,
                               t.tginitdeferred,
                               p.proname AS function_name
                          FROM pg_trigger t
                          JOIN pg_class c ON c.oid = t.tgrelid
                          JOIN pg_proc p ON p.oid = t.tgfoid
                         WHERE NOT t.tgisinternal
                           AND t.tgname LIKE 'trg_%_financial_integrity'
                        """
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()

    installed = {(row["table_name"], row["trigger_name"]) for row in rows}
    assert installed == EXPECTED_TRIGGERS
    assert all(row["tgdeferrable"] for row in rows)
    assert all(row["tginitdeferred"] for row in rows)
    assert {row["function_name"] for row in rows} == {
        "enforce_payment_financial_integrity"
    }
