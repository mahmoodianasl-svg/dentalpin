"""patient_agent module — realtime session, consent and audit foundation.

Revision ID: pag_0001
Revises: None
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "pag_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("patient_agent",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "patient_agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="created"),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("provider_session_ref", sa.String(length=255), nullable=True),
        sa.Column("locale", sa.String(length=20), nullable=True),
        sa.Column("authenticated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("handoff_state", sa.String(length=24), nullable=False, server_default="none"),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_patient_agent_sessions_clinic_id", "patient_agent_sessions", ["clinic_id"])
    op.create_index("ix_patient_agent_sessions_patient_id", "patient_agent_sessions", ["patient_id"])

    op.create_table(
        "patient_agent_consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patient_agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("consent_type", sa.String(length=40), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.String(length=40), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_patient_agent_consents_session_id", "patient_agent_consents", ["session_id"])
    op.create_index("ix_patient_agent_consents_clinic_id", "patient_agent_consents", ["clinic_id"])
    op.create_index("ix_patient_agent_consents_patient_id", "patient_agent_consents", ["patient_id"])

    op.create_table(
        "patient_agent_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patient_agent_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False, server_default="recorded"),
        sa.Column("detail", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_patient_agent_audit_events_session_id", "patient_agent_audit_events", ["session_id"])
    op.create_index("ix_patient_agent_audit_events_clinic_id", "patient_agent_audit_events", ["clinic_id"])
    op.create_index("ix_patient_agent_audit_events_patient_id", "patient_agent_audit_events", ["patient_id"])
    op.create_index("ix_patient_agent_audit_events_event_type", "patient_agent_audit_events", ["event_type"])
    op.create_index("ix_patient_agent_audit_events_created_at", "patient_agent_audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("patient_agent_audit_events")
    op.drop_table("patient_agent_consents")
    op.drop_table("patient_agent_sessions")
