"""patient_agent module — patient portal accounts.

Revision ID: pag_0004
Revises: pag_0003
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "pag_0004"
down_revision: str | None = "pag_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "patient_portal_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clinic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clinics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("clinic_id", "email", name="uq_patient_portal_accounts_clinic_email"),
        sa.UniqueConstraint("patient_id", name="uq_patient_portal_accounts_patient_id"),
    )
    op.create_index(
        "ix_patient_portal_accounts_clinic_id", "patient_portal_accounts", ["clinic_id"]
    )
    op.create_index(
        "ix_patient_portal_accounts_patient_id", "patient_portal_accounts", ["patient_id"]
    )
    op.create_index("ix_patient_portal_accounts_email", "patient_portal_accounts", ["email"])
    op.create_index(
        "ix_patient_portal_accounts_is_active", "patient_portal_accounts", ["is_active"]
    )


def downgrade() -> None:
    op.drop_table("patient_portal_accounts")
