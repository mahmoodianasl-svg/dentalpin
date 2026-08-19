"""budget — index tenant-scoped history reads.

Revision ID: bud_0005
Revises: bud_0004
Create Date: 2026-08-19

Budget history is always loaded for one clinic and budget, newest first. The
composite B-tree index covers both predicates and the chronological scan.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "bud_0005"
down_revision: str | None = "bud_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_budget_history_clinic_budget_changed",
        "budget_history",
        ["clinic_id", "budget_id", "changed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_budget_history_clinic_budget_changed",
        table_name="budget_history",
    )
