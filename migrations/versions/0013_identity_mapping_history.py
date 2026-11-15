"""Add append-only identity mapping history."""

import sqlalchemy as sa
from alembic import op

revision = "0013_identity_mapping_history"
down_revision = "0012_worker_job_claim_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Identity mapping history migration requires PostgreSQL.")

    op.create_table(
        "identity_mapping_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_customer_id", sa.String(64), nullable=False),
        sa.Column("golden_customer_id", sa.String(36), nullable=False),
        sa.Column("registry_version", sa.String(64), nullable=False),
        sa.Column("source_batch_id", sa.String(64), nullable=False),
        sa.Column("assignment_type", sa.String(24), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["golden_customer_id"],
            ["identity.golden_customers.golden_customer_id"],
        ),
        sa.ForeignKeyConstraint(
            ["registry_version"],
            ["identity.registry_versions.version_tag"],
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["core.users.id"]),
        schema="identity",
    )

    op.create_index(
        "ix_identity_mapping_history_asof",
        "identity_mapping_history",
        ["source_customer_id", "effective_at", "recorded_at"],
        schema="identity",
    )

    # Baseline records the mapping state at migration time.
    # It does not claim to reconstruct changes before this migration.
    op.execute(
        sa.text(
            """
            INSERT INTO identity.identity_mapping_history (
                source_customer_id,
                golden_customer_id,
                registry_version,
                source_batch_id,
                assignment_type,
                event_type,
                effective_at,
                recorded_at,
                reviewer_id,
                correlation_id,
                change_reason
            )
            SELECT
                source_customer_id,
                golden_customer_id,
                registry_version,
                source_batch_id,
                assignment_type,
                'BASELINE',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                NULL,
                NULL,
                'Initial baseline captured during migration 0013'
            FROM identity.source_identity_mapping
            """
        )
    )

    op.execute(
        """
        CREATE TRIGGER enforce_append_only
        BEFORE UPDATE OR DELETE
        ON identity.identity_mapping_history
        FOR EACH ROW
        EXECUTE FUNCTION gov.reject_audit_mutation()
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Downgrade requires PostgreSQL.")

    op.execute(
        """
        DROP TRIGGER enforce_append_only
        ON identity.identity_mapping_history
        """
    )
    op.drop_table("identity_mapping_history", schema="identity")
