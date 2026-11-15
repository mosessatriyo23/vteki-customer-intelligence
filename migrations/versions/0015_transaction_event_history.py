"""Add append-only transaction event history."""

import sqlalchemy as sa
from alembic import op

revision = "0015_transaction_event_history"
down_revision = "0014_identity_batch_assignment_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Transaction event history migration requires PostgreSQL.")

    op.create_table(
        "transaction_event_history",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column(
            "source_transaction_id",
            sa.String(64),
            sa.ForeignKey(
                "source.transactions.source_transaction_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "source_batch_id",
            sa.String(64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column(
            "corrects_event_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "source.transaction_event_history.event_id",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_transaction_event_idempotency",
        ),
        sa.CheckConstraint(
            "event_type IN "
            "('TRANSACTION_RECORDED', 'REFUND_RECORDED', "
            "'STATUS_CHANGED', 'CORRECTION')",
            name="ck_transaction_event_type",
        ),
        schema="source",
    )

    op.create_index(
        "ix_transaction_event_asof",
        "transaction_event_history",
        ["source_transaction_id", "occurred_at", "recorded_at"],
        schema="source",
    )
    op.create_index(
        "ix_transaction_event_available",
        "transaction_event_history",
        ["available_at"],
        schema="source",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION
        source.set_transaction_event_recorded_at()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.recorded_at := clock_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE TRIGGER set_transaction_event_recorded_at
        BEFORE INSERT ON source.transaction_event_history
        FOR EACH ROW
        EXECUTE FUNCTION source.set_transaction_event_recorded_at()
        """
    )

    op.execute(
        """
        CREATE TRIGGER enforce_append_only
        BEFORE UPDATE OR DELETE ON source.transaction_event_history
        FOR EACH ROW
        EXECUTE FUNCTION gov.reject_audit_mutation()
        """
    )

    # Existing transaction rows become baseline events.
    # This records their current snapshot, not historical refund changes.
    op.execute(
        """
        INSERT INTO source.transaction_event_history (
            source_transaction_id,
            event_type,
            occurred_at,
            available_at,
            source_batch_id,
            idempotency_key,
            payload
        )
        SELECT
            t.source_transaction_id,
            'TRANSACTION_RECORDED',
            t.transaction_datetime,
            t.created_at,
            t.source_batch_id,
            'baseline:' || t.source_transaction_id,
            jsonb_build_object(
                'source_system', t.source_system,
                'status', t.status,
                'gross_amount', t.gross_amount,
                'discount_amount', t.discount_amount,
                'net_amount', t.net_amount,
                'refund_amount', t.refund_amount,
                'actual_revenue', t.actual_revenue
            )
        FROM source.transactions AS t
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS enforce_append_only
        ON source.transaction_event_history
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS set_transaction_event_recorded_at
        ON source.transaction_event_history
        """
    )
    op.drop_index(
        "ix_transaction_event_available",
        table_name="transaction_event_history",
        schema="source",
    )
    op.drop_index(
        "ix_transaction_event_asof",
        table_name="transaction_event_history",
        schema="source",
    )
    op.drop_table("transaction_event_history", schema="source")
    op.execute("DROP FUNCTION IF EXISTS source.set_transaction_event_recorded_at()")
