"""Mark browser sessions created after successful staff MFA verification."""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("refresh_sessions", sa.Column("mfa_verified_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("refresh_sessions", "mfa_verified_at")
