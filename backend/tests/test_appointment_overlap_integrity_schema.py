"""W0.3 appointment-overlap PostgreSQL catalog contract."""

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

EXPECTED_CONSTRAINTS = {
    "ck_appointment_time_order": "c",
    "excl_appointment_professional_overlap": "x",
    "excl_appointment_cabinet_overlap": "x",
}


@pytest.mark.asyncio
async def test_appointment_overlap_constraints_are_range_based_and_partial() -> None:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT conname,
                                   contype::text AS contype,
                                   pg_get_constraintdef(oid) AS definition
                             FROM pg_constraint
                             WHERE conrelid = 'appointments'::regclass
                               AND conname IN (
                                   'ck_appointment_time_order',
                                   'excl_appointment_professional_overlap',
                                   'excl_appointment_cabinet_overlap'
                               )
                             ORDER BY conname
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
    finally:
        await engine.dispose()

    constraints = {row["conname"]: row for row in rows}
    assert {name: row["contype"] for name, row in constraints.items()} == (EXPECTED_CONSTRAINTS)

    time_order = constraints["ck_appointment_time_order"]["definition"]
    assert "start_time < end_time" in time_order

    professional = constraints["excl_appointment_professional_overlap"]["definition"]
    assert "EXCLUDE USING gist" in professional
    assert "clinic_id WITH =" in professional
    assert "professional_id WITH =" in professional
    assert "tstzrange(start_time, end_time, '[)'::text) WITH &&" in professional
    for terminal_status in ("cancelled", "completed", "no_show"):
        assert terminal_status in professional

    cabinet = constraints["excl_appointment_cabinet_overlap"]["definition"]
    assert "EXCLUDE USING gist" in cabinet
    assert "clinic_id WITH =" in cabinet
    assert "cabinet_id WITH =" in cabinet
    assert "tstzrange(start_time, end_time, '[)'::text) WITH &&" in cabinet
    assert "cabinet_id IS NOT NULL" in cabinet
    for terminal_status in ("cancelled", "completed", "no_show"):
        assert terminal_status in cabinet
