"""patient_agent module — one-time appointment confirmation proposals.

Revision ID: pag_0002
Revises: pag_0001
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "pag_0002"
down_revision: str | None = "pag_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "patient_agent_appointment_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("professional_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("jti", name="uq_patient_agent_appointment_proposals_jti"),
    )
    op.create_index(
        "ix_patient_agent_appointment_proposals_jti",
        "patient_agent_appointment_proposals",
        ["jti"],
        unique=True,
    )
    op.create_index(
        "ix_patient_agent_appointment_proposals_clinic_id",
        "patient_agent_appointment_proposals",
        ["clinic_id"],
    )
    op.create_index(
        "ix_patient_agent_appointment_proposals_patient_id",
        "patient_agent_appointment_proposals",
        ["patient_id"],
    )
    op.create_index(
        "ix_patient_agent_appointment_proposals_professional_id",
        "patient_agent_appointment_proposals",
        ["professional_id"],
    )
    op.create_index(
        "ix_patient_agent_appointment_proposals_expires_at",
        "patient_agent_appointment_proposals",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("patient_agent_appointment_proposals")
