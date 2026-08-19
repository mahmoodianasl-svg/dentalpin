"""W0.3 append-only financial/public-decision evidence contract."""

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

EXPECTED_TRIGGERS = {
    "payment_history": (
        "trg_payment_history_append_only",
        "reject_payment_history_mutation",
    ),
    "invoice_history": (
        "trg_invoice_history_append_only",
        "reject_billing_history_mutation",
    ),
    "invoice_series_history": (
        "trg_invoice_series_history_append_only",
        "reject_billing_history_mutation",
    ),
    "budget_history": (
        "trg_budget_history_append_only",
        "reject_budget_evidence_mutation",
    ),
    "budget_signatures": (
        "trg_budget_signatures_append_only",
        "reject_budget_evidence_mutation",
    ),
}

EXPECTED_RESTRICTED_FOREIGN_KEYS = {
    ("payment_history", "payment_history_payment_id_fkey"),
    ("invoice_history", "invoice_history_invoice_id_fkey"),
    ("invoice_series_history", "invoice_series_history_series_id_fkey"),
    ("budget_history", "budget_history_budget_id_fkey"),
    ("budget_signatures", "budget_signatures_budget_id_fkey"),
}


@pytest.mark.asyncio
async def test_financial_audit_evidence_is_append_only_and_parent_restricted() -> None:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            trigger_rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT table_class.relname AS table_name,
                                   trigger.tgname AS trigger_name,
                                   procedure.proname AS function_name,
                                   pg_get_triggerdef(trigger.oid) AS definition
                              FROM pg_trigger trigger
                              JOIN pg_class table_class
                                ON table_class.oid = trigger.tgrelid
                              JOIN pg_proc procedure
                                ON procedure.oid = trigger.tgfoid
                             WHERE NOT trigger.tgisinternal
                               AND trigger.tgname IN (
                                   'trg_payment_history_append_only',
                                   'trg_invoice_history_append_only',
                                   'trg_invoice_series_history_append_only',
                                   'trg_budget_history_append_only',
                                   'trg_budget_signatures_append_only'
                               )
                             ORDER BY table_class.relname
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
            foreign_key_rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT constraint_row.conrelid::regclass::text AS table_name,
                                   constraint_row.conname AS constraint_name,
                                   constraint_row.confdeltype::text AS delete_action
                              FROM pg_constraint constraint_row
                             WHERE constraint_row.contype = 'f'
                               AND constraint_row.conname IN (
                                   'payment_history_payment_id_fkey',
                                   'invoice_history_invoice_id_fkey',
                                   'invoice_series_history_series_id_fkey',
                                   'budget_history_budget_id_fkey',
                                   'budget_signatures_budget_id_fkey'
                               )
                             ORDER BY constraint_row.conname
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
    finally:
        await engine.dispose()

    installed_triggers = {
        row["table_name"]: (row["trigger_name"], row["function_name"]) for row in trigger_rows
    }
    assert installed_triggers == EXPECTED_TRIGGERS
    for row in trigger_rows:
        definition = row["definition"]
        assert "BEFORE" in definition
        assert "UPDATE" in definition
        assert "DELETE" in definition
        assert "FOR EACH ROW" in definition

    installed_foreign_keys = {
        (row["table_name"], row["constraint_name"]): row["delete_action"]
        for row in foreign_key_rows
    }
    assert set(installed_foreign_keys) == EXPECTED_RESTRICTED_FOREIGN_KEYS
    assert set(installed_foreign_keys.values()) == {"r"}
