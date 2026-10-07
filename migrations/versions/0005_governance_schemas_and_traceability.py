import sqlalchemy as sa
from alembic import op

revision = "0005_governance_schemas_and_traceability"
down_revision = "0004_customer_campaigns"
branch_labels = None
depends_on = None

SCHEMAS = ["core", "stg", "feat", "ml", "dec", "act", "msr", "gov"]


def upgrade() -> None:
    # 1. Create partitioned schemas if on PostgreSQL
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for schema in SCHEMAS:
            bind.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

    # 2. Add correlation_id to audit_events
    op.add_column(
        "audit_events", sa.Column("correlation_id", sa.String(length=64), nullable=True)
    )
    op.create_index(
        "ix_audit_events_correlation_id", "audit_events", ["correlation_id"]
    )

    # 3. Create identity_reviews table
    op.create_table(
        "identity_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(length=32), nullable=False),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("flagged_reason", sa.String(length=256), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="Pending"
        ),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_identity_reviews_customer_code", "identity_reviews", ["customer_code"]
    )
    op.create_index("ix_identity_reviews_status", "identity_reviews", ["status"])

    # 4. Create human_overrides table
    op.create_table(
        "human_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("original_nba", sa.String(length=256), nullable=False),
        sa.Column("override_nba", sa.String(length=256), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("overridden_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_human_overrides_customer_id", "human_overrides", ["customer_id"]
    )

    # 5. Create model_drift_logs table
    op.create_table(
        "model_drift_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("psi_score", sa.Float(), nullable=False),
        sa.Column("drift_status", sa.String(length=32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 6. Create decision_traces table
    op.create_table(
        "decision_traces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("customer_code", sa.String(length=32), nullable=False),
        sa.Column("trigger_event", sa.String(length=128), nullable=False),
        sa.Column("decision_output", sa.String(length=256), nullable=False),
        sa.Column("step_logs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_decision_traces_correlation_id", "decision_traces", ["correlation_id"]
    )
    op.create_index(
        "ix_decision_traces_customer_code", "decision_traces", ["customer_code"]
    )


def downgrade() -> None:
    op.drop_index("ix_decision_traces_customer_code", table_name="decision_traces")
    op.drop_index("ix_decision_traces_correlation_id", table_name="decision_traces")
    op.drop_table("decision_traces")
    op.drop_table("model_drift_logs")
    op.drop_index("ix_human_overrides_customer_id", table_name="human_overrides")
    op.drop_table("human_overrides")
    op.drop_index("ix_identity_reviews_status", table_name="identity_reviews")
    op.drop_index("ix_identity_reviews_customer_code", table_name="identity_reviews")
    op.drop_table("identity_reviews")
    op.drop_index("ix_audit_events_correlation_id", table_name="audit_events")
    op.drop_column("audit_events", "correlation_id")
