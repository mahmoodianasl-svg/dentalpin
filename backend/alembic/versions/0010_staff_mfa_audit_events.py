"""Record account-scoped MFA security events without credential material."""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staff_mfa_audit_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_staff_mfa_audit_events_user_created",
        "staff_mfa_audit_events",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_staff_mfa_audit_events_user_created", table_name="staff_mfa_audit_events")
    op.drop_table("staff_mfa_audit_events")
