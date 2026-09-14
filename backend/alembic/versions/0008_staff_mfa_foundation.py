"""Prepare isolated storage for staff MFA without changing login behavior.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staff_mfa_factors",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column("pending_expires_at", sa.DateTime(timezone=True)),
        sa.Column("enrolled_at", sa.DateTime(timezone=True)),
        sa.Column("last_accepted_step", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "staff_mfa_challenges",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("challenge_hash", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("challenge_hash"),
    )
    op.create_index("ix_staff_mfa_challenges_user_id", "staff_mfa_challenges", ["user_id"])
    op.create_table(
        "staff_mfa_recovery_codes",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(
        "ix_staff_mfa_recovery_codes_user_id", "staff_mfa_recovery_codes", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_staff_mfa_recovery_codes_user_id", table_name="staff_mfa_recovery_codes")
    op.drop_table("staff_mfa_recovery_codes")
    op.drop_index("ix_staff_mfa_challenges_user_id", table_name="staff_mfa_challenges")
    op.drop_table("staff_mfa_challenges")
    op.drop_table("staff_mfa_factors")
