"""billing — make invoice audit histories append-only evidence.

Revision ID: bil_0007
Revises: bil_0006
Create Date: 2026-08-19

Invoice and series corrections must add history rather than rewrite it. Parent
deletion is restricted so cascade behavior cannot erase compliance evidence.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "bil_0007"
down_revision: str | None = "bil_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM invoice_history history
                  LEFT JOIN invoices invoice ON invoice.id = history.invoice_id
                 WHERE invoice.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot protect invoice history: orphaned invoice_history rows exist';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM invoice_series_history history
                  LEFT JOIN invoice_series series ON series.id = history.series_id
                 WHERE series.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot protect invoice series history: orphaned history rows exist';
            END IF;
        END
        $$;
        """
    )

    for table_name, column_name, parent_table in (
        ("invoice_history", "invoice_id", "invoices"),
        ("invoice_series_history", "series_id", "invoice_series"),
    ):
        constraint_name = f"{table_name}_{column_name}_fkey"
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            table_name,
            parent_table,
            [column_name],
            ["id"],
            ondelete="RESTRICT",
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_billing_history_mutation()
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
    for table_name in ("invoice_history", "invoice_series_history"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION reject_billing_history_mutation(
                'ck_{table_name}_append_only'
            );
            """
        )


def downgrade() -> None:
    for table_name in ("invoice_series_history", "invoice_history"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS reject_billing_history_mutation()")

    for table_name, column_name, parent_table in (
        ("invoice_series_history", "series_id", "invoice_series"),
        ("invoice_history", "invoice_id", "invoices"),
    ):
        constraint_name = f"{table_name}_{column_name}_fkey"
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            table_name,
            parent_table,
            [column_name],
            ["id"],
            ondelete="CASCADE",
        )
