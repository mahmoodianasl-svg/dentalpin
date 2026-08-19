"""recalls — index tenant-scoped contact-attempt history reads.

Revision ID: rec_0002
Revises: rec_0001
Create Date: 2026-08-19

Recall detail and attempt-list endpoints filter by clinic and recall before
ordering by attempt time. One composite index serves that exact access path.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "rec_0002"
down_revision: str | None = "rec_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_recall_attempts_clinic_recall_attempted",
        "recall_contact_attempts",
        ["clinic_id", "recall_id", "attempted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recall_attempts_clinic_recall_attempted",
        table_name="recall_contact_attempts",
    )
