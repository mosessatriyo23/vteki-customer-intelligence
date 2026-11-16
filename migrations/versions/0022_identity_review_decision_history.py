
"""Add bitemporal identity review decision history."""

import sqlalchemy as sa
from alembic import op

revision = "0022_identity_review_decision_history"
down_revision = "0021_batch_job_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0022 requires PostgreSQL.")

    op.create_table(
        "review_decision_history",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "review_queue_id",
            sa.BigInteger(),
            sa.ForeignKey("identity.review_queue.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("action", sa.String(32), nullable=True),
        sa.Column(
            "supersedes_event_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "identity.review_decision_history.event_id", ondelete="RESTRICT"
            ),
            nullable=True,
        ),
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
            sa.ForeignKey("stg.ingestion_batches.batch_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("source_version", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column(
            "reviewer_id",
            sa.Integer(),
            sa.ForeignKey("core.users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("rationale", sa.String(1000), nullable=False),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_review_decision_idempotency",
        ),
        sa.CheckConstraint(
            "event_type IN ('DECISION', 'CORRECTION', 'REVOCATION')",
            name="ck_review_decision_history_event_type",
        ),
        sa.CheckConstraint(
            "(event_type = 'REVOCATION' AND action IS NULL) OR "
            "(event_type IN ('DECISION', 'CORRECTION') AND action IN "
            "('APPROVE_MERGE', 'REJECT_KEEP_SEPARATE'))",
            name="ck_review_decision_history_action",
        ),
        schema="identity",
    )

    op.create_index(
        "ix_review_decision_history_asof",
        "review_decision_history",
        ["review_queue_id", "occurred_at", "available_at", "recorded_at"],
        schema="identity",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION identity.set_review_decision_receipt_time()
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
        CREATE TRIGGER set_review_decision_receipt_time
        BEFORE INSERT ON identity.review_decision_history
        FOR EACH ROW
        EXECUTE FUNCTION identity.set_review_decision_receipt_time()
        """
    )

    op.execute(
        """
        CREATE TRIGGER enforce_append_only
        BEFORE UPDATE OR DELETE ON identity.review_decision_history
        FOR EACH ROW
        EXECUTE FUNCTION gov.reject_audit_mutation()
        """
    )

    # Preserve legacy decisions. Their historical availability is unknown,
    # so availability is fenced at migration time.
    op.execute(
        """
        INSERT INTO identity.review_decision_history (
            review_queue_id, event_type, action, supersedes_event_id,
            occurred_at, available_at, source_batch_id, source_event_id,
            source_version, idempotency_key,
            reviewer_id, correlation_id, rationale
        )
        SELECT DISTINCT ON (a.review_queue_id)
            a.review_queue_id,
            'DECISION',
            a.action,
            NULL,
            a.performed_at,
            clock_timestamp(),
            q.source_batch_id,
            'legacy-review:' || a.id::text,
            'legacy-audit-v1',
            'legacy-review:' || a.review_queue_id::text || ':' || a.id::text,
            a.actor_id,
            a.correlation_id,
            a.rationale
        FROM identity.review_audit_log AS a
        JOIN identity.review_queue AS q
            ON q.id = a.review_queue_id
        WHERE a.action IN ('APPROVE_MERGE', 'REJECT_KEEP_SEPARATE')
        ORDER BY a.review_queue_id, a.performed_at, a.id
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0022 requires PostgreSQL.")

    op.execute(
        "DROP TRIGGER IF EXISTS enforce_append_only "
        "ON identity.review_decision_history"
    )

    op.execute(
        "DROP TRIGGER IF EXISTS set_review_decision_receipt_time "
        "ON identity.review_decision_history"
    )

    op.drop_table("review_decision_history", schema="identity")

    op.execute(
        "DROP FUNCTION IF EXISTS identity.set_review_decision_receipt_time()"
    )
