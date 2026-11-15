"""Persist identity history coverage independently of baseline row count."""

import sqlalchemy as sa
from alembic import op

revision = "0023_identity_history_coverage_marker"
down_revision = "0022_identity_review_decision_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0023 requires PostgreSQL.")

    op.create_table(
        "identity_history_coverage",
        sa.Column("singleton_id", sa.Integer(), primary_key=True),
        sa.Column("coverage_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "singleton_id = 1", name="ck_identity_history_coverage_singleton"
        ),
        schema="identity",
    )
    op.execute(
        """
        INSERT INTO identity.identity_history_coverage (
            singleton_id, coverage_started_at, recorded_at
        )
        SELECT
            1,
            COALESCE(
                MIN(recorded_at) FILTER (
                    WHERE event_type = 'BASELINE'
                      AND change_reason = 'Initial baseline captured during migration 0013'
                ),
                clock_timestamp()
            ),
            clock_timestamp()
        FROM identity.identity_mapping_history
        """
    )
    op.execute(
        """
        CREATE TRIGGER enforce_append_only
        BEFORE UPDATE OR DELETE ON identity.identity_history_coverage
        FOR EACH ROW
        EXECUTE FUNCTION gov.reject_audit_mutation()
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0023 requires PostgreSQL.")
    op.execute(
        "DROP TRIGGER IF EXISTS enforce_append_only "
        "ON identity.identity_history_coverage"
    )
    op.drop_table("identity_history_coverage", schema="identity")
