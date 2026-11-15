"""Add transaction event provenance and enforce receipt-time availability."""

import sqlalchemy as sa
from alembic import op

revision = "0016_transaction_event_provenance"
down_revision = "0015_transaction_event_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0016 requires PostgreSQL.")

    op.add_column(
        "transaction_event_history",
        sa.Column("actor_type", sa.String(16), nullable=True),
        schema="source",
    )
    op.add_column(
        "transaction_event_history",
        sa.Column("actor_id", sa.String(128), nullable=True),
        schema="source",
    )
    op.add_column(
        "transaction_event_history",
        sa.Column("source_event_id", sa.String(128), nullable=True),
        schema="source",
    )
    op.add_column(
        "transaction_event_history",
        sa.Column("source_version", sa.String(64), nullable=True),
        schema="source",
    )

    op.create_check_constraint(
        "ck_transaction_event_actor_type",
        "transaction_event_history",
        "actor_type IS NULL OR actor_type IN ('USER','SYSTEM','WORKER','SOURCE')",
        schema="source",
    )

    op.create_index(
        "ix_transaction_event_source_version",
        "transaction_event_history",
        ["source_event_id", "source_version"],
        schema="source",
    )

    # Existing baseline rows retain their historical available_at.
    # New rows always receive database time and cannot be backdated.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
        source.set_transaction_event_receipt_time()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.available_at := clock_timestamp();
            NEW.recorded_at := NEW.available_at;
            RETURN NEW;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE TRIGGER set_transaction_event_receipt_time
        BEFORE INSERT ON source.transaction_event_history
        FOR EACH ROW
        EXECUTE FUNCTION source.set_transaction_event_receipt_time()
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        DROP TRIGGER IF EXISTS set_transaction_event_receipt_time
        ON source.transaction_event_history
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS source.set_transaction_event_receipt_time()
        """
    )

    op.drop_index(
        "ix_transaction_event_source_version",
        table_name="transaction_event_history",
        schema="source",
    )
    op.drop_constraint(
        "ck_transaction_event_actor_type",
        "transaction_event_history",
        schema="source",
        type_="check",
    )

    op.drop_column("transaction_event_history", "source_version", schema="source")
    op.drop_column("transaction_event_history", "source_event_id", schema="source")
    op.drop_column("transaction_event_history", "actor_id", schema="source")
    op.drop_column("transaction_event_history", "actor_type", schema="source")
