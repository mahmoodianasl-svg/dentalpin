"""billing — allow one default invoice series per clinic and type.

Revision ID: bil_0006
Revises: bil_0005
Create Date: 2026-08-18

The service layer selects a default series by clinic and series type. A partial
unique index makes that lookup deterministic under concurrent writes while
allowing any number of non-default series.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "bil_0006"
down_revision: str | None = "bil_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            duplicate_record record;
        BEGIN
            SELECT clinic_id, series_type, COUNT(*) AS default_count
              INTO duplicate_record
              FROM invoice_series
             WHERE is_default IS TRUE
             GROUP BY clinic_id, series_type
            HAVING COUNT(*) > 1
             LIMIT 1;

            IF FOUND THEN
                RAISE EXCEPTION
                    'cannot enforce default invoice series uniqueness: clinic %, type % has % defaults',
                    duplicate_record.clinic_id,
                    duplicate_record.series_type,
                    duplicate_record.default_count;
            END IF;
        END
        $$;
        """
    )
    op.create_index(
        "uq_invoice_series_default_per_type",
        "invoice_series",
        ["clinic_id", "series_type"],
        unique=True,
        postgresql_where="is_default IS TRUE",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_invoice_series_default_per_type",
        table_name="invoice_series",
    )
