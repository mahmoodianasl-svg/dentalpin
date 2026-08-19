"""payments — make payment history append-only evidence.

Revision ID: pay_0006
Revises: pay_0005
Create Date: 2026-08-19

Payment corrections are represented by new allocation/refund actions and new
history rows. Existing history must therefore be neither rewritten nor erased,
including indirectly through deletion of its parent payment.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "pay_0006"
down_revision: str | None = "pay_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM payment_history history
                  LEFT JOIN payments payment ON payment.id = history.payment_id
                 WHERE payment.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot protect payment history: orphaned payment_history rows exist';
            END IF;
        END
        $$;
        """
    )

    op.drop_constraint(
        "payment_history_payment_id_fkey",
        "payment_history",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "payment_history_payment_id_fkey",
        "payment_history",
        "payments",
        ["payment_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_payment_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only; % is forbidden', TG_TABLE_NAME, TG_OP
                USING ERRCODE = '23514', CONSTRAINT = TG_ARGV[0];
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payment_history_append_only
        BEFORE UPDATE OR DELETE ON payment_history
        FOR EACH ROW
        EXECUTE FUNCTION reject_payment_history_mutation('ck_payment_history_append_only');
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_payment_history_append_only ON payment_history")
    op.execute("DROP FUNCTION IF EXISTS reject_payment_history_mutation()")

    op.drop_constraint(
        "payment_history_payment_id_fkey",
        "payment_history",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "payment_history_payment_id_fkey",
        "payment_history",
        "payments",
        ["payment_id"],
        ["id"],
        ondelete="CASCADE",
    )
