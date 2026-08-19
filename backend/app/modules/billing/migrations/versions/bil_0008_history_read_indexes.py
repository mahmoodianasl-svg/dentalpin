"""billing — index tenant-scoped audit history reads.

Revision ID: bil_0008
Revises: bil_0007
Create Date: 2026-08-19

Invoice and series history endpoints filter by clinic and parent before
ordering by change time. Composite B-tree indexes satisfy that complete read
shape and can be scanned backward for newest-first responses.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "bil_0008"
down_revision: str | None = "bil_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_invoice_history_clinic_invoice_changed",
        "invoice_history",
        ["clinic_id", "invoice_id", "changed_at"],
        unique=False,
    )
    op.create_index(
        "idx_invoice_series_history_clinic_series_changed",
        "invoice_series_history",
        ["clinic_id", "series_id", "changed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_invoice_series_history_clinic_series_changed",
        table_name="invoice_series_history",
    )
    op.drop_index(
        "idx_invoice_history_clinic_invoice_changed",
        table_name="invoice_history",
    )
