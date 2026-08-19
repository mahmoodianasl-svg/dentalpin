"""Enforce appointment range and overlap integrity.

The legacy partial unique index protected only an exact
``(clinic, cabinet, professional, start_time)`` tuple. It allowed a
professional to be double-booked in different cabinets, a cabinet to be
double-booked across professionals, and any overlap whose start times differed.

This migration fails closed when existing active appointments violate the new
contract, then replaces the tuple index with half-open PostgreSQL range
exclusions. Back-to-back appointments remain valid. Terminal appointments are
historical and do not reserve a slot, preserving the ``ag_0004`` semantics.

Revision ID: ag_0007
Revises: ag_0006
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ag_0007"
down_revision: str | None = "ag_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_PREDICATE = "status NOT IN ('cancelled', 'completed', 'no_show')"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                      FROM appointments
                     WHERE start_time >= end_time
                ) THEN
                    RAISE EXCEPTION
                        'ag_0007 preflight failed: appointments contain non-positive time ranges';
                END IF;

                IF EXISTS (
                    SELECT 1
                      FROM appointments left_appointment
                      JOIN appointments right_appointment
                        ON left_appointment.id < right_appointment.id
                       AND left_appointment.clinic_id = right_appointment.clinic_id
                       AND left_appointment.professional_id = right_appointment.professional_id
                       AND left_appointment.start_time < right_appointment.end_time
                       AND right_appointment.start_time < left_appointment.end_time
                     WHERE left_appointment.status
                               NOT IN ('cancelled', 'completed', 'no_show')
                       AND right_appointment.status
                               NOT IN ('cancelled', 'completed', 'no_show')
                ) THEN
                    RAISE EXCEPTION
                        'ag_0007 preflight failed: active professional appointments overlap';
                END IF;

                IF EXISTS (
                    SELECT 1
                      FROM appointments left_appointment
                      JOIN appointments right_appointment
                        ON left_appointment.id < right_appointment.id
                       AND left_appointment.clinic_id = right_appointment.clinic_id
                       AND left_appointment.cabinet_id = right_appointment.cabinet_id
                       AND left_appointment.start_time < right_appointment.end_time
                       AND right_appointment.start_time < left_appointment.end_time
                     WHERE left_appointment.cabinet_id IS NOT NULL
                       AND left_appointment.status
                               NOT IN ('cancelled', 'completed', 'no_show')
                       AND right_appointment.status
                               NOT IN ('cancelled', 'completed', 'no_show')
                ) THEN
                    RAISE EXCEPTION
                        'ag_0007 preflight failed: active cabinet appointments overlap';
                END IF;
            END
            $$
            """
        )
    )

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.drop_index("idx_appointment_slot", table_name="appointments")
    op.create_check_constraint(
        "ck_appointment_time_order",
        "appointments",
        "start_time < end_time",
    )
    op.execute(
        sa.text(
            f"""
            ALTER TABLE appointments
            ADD CONSTRAINT excl_appointment_professional_overlap
            EXCLUDE USING gist (
                clinic_id WITH =,
                professional_id WITH =,
                tstzrange(start_time, end_time, '[)') WITH &&
            )
            WHERE ({ACTIVE_PREDICATE})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            ALTER TABLE appointments
            ADD CONSTRAINT excl_appointment_cabinet_overlap
            EXCLUDE USING gist (
                clinic_id WITH =,
                cabinet_id WITH =,
                tstzrange(start_time, end_time, '[)') WITH &&
            )
            WHERE ({ACTIVE_PREDICATE} AND cabinet_id IS NOT NULL)
            """
        )
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT excl_appointment_cabinet_overlap")
    op.execute("ALTER TABLE appointments DROP CONSTRAINT excl_appointment_professional_overlap")
    op.drop_constraint(
        "ck_appointment_time_order",
        "appointments",
        type_="check",
    )
    op.create_index(
        "idx_appointment_slot",
        "appointments",
        ["clinic_id", "cabinet_id", "professional_id", "start_time"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_PREDICATE),
    )

    # Deliberately retain btree_gist: it is a database-scoped shared extension,
    # and dropping it could break unrelated operator classes installed later.
