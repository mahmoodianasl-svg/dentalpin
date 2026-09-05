"""patient_agent module — persistent curated dental knowledge.

Revision ID: pag_0003
Revises: pag_0002
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "pag_0003"
down_revision: str | None = "pag_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "patient_agent_dental_knowledge",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clinic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clinics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("topic", sa.String(length=40), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("review_status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("clinically_reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "approved_for_patient_education",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "clinic_id",
            "entry_key",
            "version",
            name="uq_patient_agent_dental_knowledge_clinic_entry_version",
        ),
    )
    op.create_index(
        "ix_patient_agent_dental_knowledge_clinic_id",
        "patient_agent_dental_knowledge",
        ["clinic_id"],
    )
    op.create_index(
        "ix_patient_agent_dental_knowledge_entry_key",
        "patient_agent_dental_knowledge",
        ["entry_key"],
    )
    op.create_index(
        "ix_patient_agent_dental_knowledge_topic",
        "patient_agent_dental_knowledge",
        ["topic"],
    )
    op.create_index(
        "ix_patient_agent_dental_knowledge_locale",
        "patient_agent_dental_knowledge",
        ["locale"],
    )
    op.create_index(
        "ix_patient_agent_dental_knowledge_review_status",
        "patient_agent_dental_knowledge",
        ["review_status"],
    )
    op.create_index(
        "ix_patient_agent_dental_knowledge_active",
        "patient_agent_dental_knowledge",
        ["active"],
    )


def downgrade() -> None:
    op.drop_table("patient_agent_dental_knowledge")
