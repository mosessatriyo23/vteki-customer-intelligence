"""Persist bitemporal visit and membership source events."""

import sqlalchemy as sa
from alembic import op

revision = "0020_business_event_history"
down_revision = "0019_transaction_event_origin_batch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0020 requires PostgreSQL.")

    op.create_table(
        "business_event_history",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("source_version", sa.String(64), nullable=False),
        sa.Column("source_customer_ref", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "source_batch_id",
            sa.String(64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("lineage_reference", sa.String(128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_business_event_history_idempotency",
        ),
        sa.CheckConstraint(
            "subject_type IN ('VISIT', 'MEMBERSHIP')",
            name="ck_business_event_history_subject",
        ),
        sa.CheckConstraint(
            "event_type IN "
            "('VISIT_COMPLETED', 'MEMBERSHIP_JOIN', 'MEMBERSHIP_RENEWAL')",
            name="ck_business_event_history_type",
        ),
        schema="source",
    )
    op.create_index(
        "ix_business_event_history_asof",
        "business_event_history",
        ["source_customer_ref", "occurred_at", "available_at"],
        schema="source",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION source.set_business_event_receipt_time()
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
        CREATE TRIGGER set_business_event_receipt_time
        BEFORE INSERT ON source.business_event_history
        FOR EACH ROW
        EXECUTE FUNCTION source.set_business_event_receipt_time()
        """
    )
    op.execute(
        """
        CREATE TRIGGER enforce_append_only
        BEFORE UPDATE OR DELETE ON source.business_event_history
        FOR EACH ROW
        EXECUTE FUNCTION gov.reject_audit_mutation()
        """
    )

    # These are the source occurrence times; availability is when this ledger
    # first captures the existing feed, not a reconstruction of past receipt.
    op.execute(
        """
        INSERT INTO source.business_event_history (
            subject_type,
            event_type,
            source_event_id,
            source_version,
            source_customer_ref,
            occurred_at,
            available_at,
            source_batch_id,
            idempotency_key,
            lineage_reference,
            payload
        )
        SELECT
            'VISIT',
            'VISIT_COMPLETED',
            visit.visit_id,
            batch.schema_version,
            visit.source_customer_ref,
            visit.visit_datetime,
            clock_timestamp(),
            visit.source_batch_id,
            visit.source_batch_id || ':customer_visits:' ||
                visit.visit_id || ':' || batch.schema_version,
            visit.source_transaction_id,
            to_jsonb(visit)
        FROM source.customer_visits AS visit
        JOIN stg.ingestion_batches AS batch
          ON batch.batch_id = visit.source_batch_id
        WHERE visit.status = 'COMPLETED'
        ON CONFLICT (idempotency_key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO source.business_event_history (
            subject_type,
            event_type,
            source_event_id,
            source_version,
            source_customer_ref,
            occurred_at,
            available_at,
            source_batch_id,
            idempotency_key,
            lineage_reference,
            payload
        )
        SELECT
            'MEMBERSHIP',
            CASE membership.event_type
                WHEN 'JOIN' THEN 'MEMBERSHIP_JOIN'
                WHEN 'RENEWAL' THEN 'MEMBERSHIP_RENEWAL'
            END,
            membership.event_id,
            batch.schema_version,
            membership.source_customer_ref,
            membership.occurred_at,
            clock_timestamp(),
            membership.source_batch_id,
            membership.source_batch_id || ':membership_events:' ||
                membership.event_id || ':' || batch.schema_version,
            membership.previous_event_id,
            to_jsonb(membership)
        FROM source.membership_events AS membership
        JOIN stg.ingestion_batches AS batch
          ON batch.batch_id = membership.source_batch_id
        ON CONFLICT (idempotency_key) DO NOTHING
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0020 requires PostgreSQL.")

    op.execute(
        """
        DROP TRIGGER IF EXISTS enforce_append_only
        ON source.business_event_history
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS set_business_event_receipt_time
        ON source.business_event_history
        """
    )
    op.drop_index(
        "ix_business_event_history_asof",
        table_name="business_event_history",
        schema="source",
    )
    op.drop_table("business_event_history", schema="source")
    op.execute("DROP FUNCTION IF EXISTS source.set_business_event_receipt_time()")
