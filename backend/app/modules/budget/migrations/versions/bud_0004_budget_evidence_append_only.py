"""budget — make history and signature evidence append-only.

Revision ID: bud_0004
Revises: bud_0003
Create Date: 2026-08-19

Budget decisions and signatures are durable evidence. Corrections add a new
event; existing rows cannot be updated, deleted, or erased by parent cascades.
Retention-managed public access logs are intentionally outside this contract.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "bud_0004"
down_revision: str | None = "bud_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM budget_history history
                  LEFT JOIN budgets budget ON budget.id = history.budget_id
                 WHERE budget.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot protect budget history: orphaned budget_history rows exist';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM budget_signatures signature
                  LEFT JOIN budgets budget ON budget.id = signature.budget_id
                 WHERE budget.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot protect budget signatures: orphaned signature rows exist';
            END IF;
        END
        $$;
        """
    )

    for table_name in ("budget_history", "budget_signatures"):
        constraint_name = f"{table_name}_budget_id_fkey"
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            table_name,
            "budgets",
            ["budget_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_budget_evidence_mutation()
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
    for table_name in ("budget_history", "budget_signatures"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION reject_budget_evidence_mutation(
                'ck_{table_name}_append_only'
            );
            """
        )


def downgrade() -> None:
    for table_name in ("budget_signatures", "budget_history"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS reject_budget_evidence_mutation()")

    for table_name in ("budget_signatures", "budget_history"):
        constraint_name = f"{table_name}_budget_id_fkey"
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            table_name,
            "budgets",
            ["budget_id"],
            ["id"],
            ondelete="CASCADE",
        )
