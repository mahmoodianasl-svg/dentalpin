"""payments — enforce allocation and refund aggregate invariants.

Revision ID: pay_0005
Revises: pay_0004
Create Date: 2026-08-17

PostgreSQL CHECK constraints cannot express aggregate rules across child rows.
Deferred constraint triggers therefore validate the final transaction state:

* every persisted payment is fully allocated; and
* cumulative refunds never exceed the payment amount.

The parent payment row is locked before aggregation. This serializes concurrent
allocation/refund writers for the same payment and closes the race left by
service-layer pre-checks.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "pay_0005"
down_revision: str | None = "pay_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fail closed if historical rows already violate either invariant.
    op.execute(
        """
        DO $$
        DECLARE
            bad_payment uuid;
        BEGIN
            SELECT p.id
              INTO bad_payment
              FROM payments p
              LEFT JOIN payment_allocations a ON a.payment_id = p.id
             GROUP BY p.id, p.amount
            HAVING COALESCE(SUM(a.amount), 0) <> p.amount
             LIMIT 1;

            IF bad_payment IS NOT NULL THEN
                RAISE EXCEPTION
                    'cannot install payment integrity guards: payment % is not fully allocated',
                    bad_payment;
            END IF;

            SELECT p.id
              INTO bad_payment
              FROM payments p
              LEFT JOIN refunds r ON r.payment_id = p.id
             GROUP BY p.id, p.amount
            HAVING COALESCE(SUM(r.amount), 0) > p.amount
             LIMIT 1;

            IF bad_payment IS NOT NULL THEN
                RAISE EXCEPTION
                    'cannot install payment integrity guards: payment % is over-refunded',
                    bad_payment;
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_payment_financial_integrity(target_payment_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            payment_amount numeric(12, 2);
            allocated_amount numeric(12, 2);
            refunded_amount numeric(12, 2);
        BEGIN
            SELECT amount
              INTO payment_amount
              FROM payments
             WHERE id = target_payment_id
             FOR UPDATE;

            -- A cascaded child delete can be checked after its parent is gone.
            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT COALESCE(SUM(amount), 0)
              INTO allocated_amount
              FROM payment_allocations
             WHERE payment_id = target_payment_id;

            IF allocated_amount <> payment_amount THEN
                RAISE EXCEPTION
                    'payment % must be fully allocated: amount %, allocated %',
                    target_payment_id, payment_amount, allocated_amount
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_payment_fully_allocated';
            END IF;

            SELECT COALESCE(SUM(amount), 0)
              INTO refunded_amount
              FROM refunds
             WHERE payment_id = target_payment_id;

            IF refunded_amount > payment_amount THEN
                RAISE EXCEPTION
                    'payment % refund total % exceeds amount %',
                    target_payment_id, refunded_amount, payment_amount
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_payment_refund_total';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_payment_financial_integrity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_TABLE_NAME = 'payments' THEN
                PERFORM check_payment_financial_integrity(
                    CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END
                );
            ELSE
                IF TG_OP IN ('UPDATE', 'DELETE') THEN
                    PERFORM check_payment_financial_integrity(OLD.payment_id);
                END IF;
                IF TG_OP IN ('INSERT', 'UPDATE')
                   AND (TG_OP <> 'UPDATE' OR NEW.payment_id IS DISTINCT FROM OLD.payment_id)
                THEN
                    PERFORM check_payment_financial_integrity(NEW.payment_id);
                END IF;
            END IF;
            RETURN NULL;
        END
        $$;
        """
    )

    for table_name in ("payments", "payment_allocations", "refunds"):
        op.execute(
            f"""
            CREATE CONSTRAINT TRIGGER trg_{table_name}_financial_integrity
            AFTER INSERT OR UPDATE OR DELETE ON {table_name}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION enforce_payment_financial_integrity();
            """
        )


def downgrade() -> None:
    for table_name in ("refunds", "payment_allocations", "payments"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_financial_integrity ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS enforce_payment_financial_integrity()")
    op.execute("DROP FUNCTION IF EXISTS check_payment_financial_integrity(uuid)")
