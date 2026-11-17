"""Separate transaction origin batch from event receiving batch."""

import sqlalchemy as sa
from alembic import op

revision = "0019_transaction_event_origin_batch"
down_revision = "0018_identity_mapping_batch_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0019 requires PostgreSQL.")

    op.add_column(
        "transaction_event_history",
        sa.Column("source_transaction_batch_id", sa.String(64), nullable=True),
        schema="source",
    )
    op.execute(
        "ALTER TABLE source.transaction_event_history "
        "DISABLE TRIGGER enforce_append_only"
    )
    op.execute(
        """
        UPDATE source.transaction_event_history AS e
        SET source_transaction_batch_id = tx.source_batch_id
        FROM source.transactions AS tx
        WHERE tx.source_transaction_id = e.source_transaction_id
        """
    )

    missing_origin = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT COUNT(*)
            FROM source.transaction_event_history
            WHERE source_transaction_batch_id IS NULL
            """
            )
        )
        .scalar_one()
    )
    if missing_origin:
        raise RuntimeError(
            "Cannot add transaction origin batch: "
            f"{missing_origin} event(s) have no source transaction."
        )

    op.execute(
        "ALTER TABLE source.transaction_event_history "
        "ENABLE TRIGGER enforce_append_only"
    )
    op.alter_column(
        "transaction_event_history",
        "source_transaction_batch_id",
        existing_type=sa.String(64),
        nullable=False,
        schema="source",
    )
    op.create_foreign_key(
        "fk_transaction_event_origin_batch",
        "transaction_event_history",
        "ingestion_batches",
        ["source_transaction_batch_id"],
        ["batch_id"],
        source_schema="source",
        referent_schema="stg",
    )
    op.create_index(
        "ix_transaction_event_origin_batch",
        "transaction_event_history",
        ["source_transaction_batch_id"],
        schema="source",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0019 requires PostgreSQL.")

    op.drop_index(
        "ix_transaction_event_origin_batch",
        table_name="transaction_event_history",
        schema="source",
    )
    op.drop_constraint(
        "fk_transaction_event_origin_batch",
        "transaction_event_history",
        schema="source",
        type_="foreignkey",
    )
    op.drop_column(
        "transaction_event_history",
        "source_transaction_batch_id",
        schema="source",
    )
