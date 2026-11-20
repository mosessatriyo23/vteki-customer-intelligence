"""Persist development-only Moses predictions for independent review."""

import sqlalchemy as sa
from alembic import op

revision = "0024_moses_prediction_review"
down_revision = "0023_identity_history_coverage_marker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0024 requires PostgreSQL.")

    op.add_column(
        "campaigns",
        sa.Column("execution_job_id", sa.Integer(), nullable=True),
        schema="act",
    )
    op.create_foreign_key(
        "fk_campaign_execution_job",
        "campaigns",
        "batch_jobs",
        ["execution_job_id"],
        ["id"],
        source_schema="act",
        referent_schema="act",
        ondelete="RESTRICT",
    )

    op.create_table(
        "prediction_review_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("feature_set_version", sa.String(128), nullable=False),
        sa.Column("label_version", sa.String(128), nullable=False),
        sa.Column("prediction_type", sa.String(64), nullable=False),
        sa.Column("producer_version", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("submitted_by", sa.Integer(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "review_status IN ('pending_review', 'reviewed', 'rejected')",
            name="ck_ml_prediction_review_status",
        ),
        sa.CheckConstraint("record_count > 0", name="ck_ml_prediction_record_count"),
        schema="ml",
    )
    op.create_index(
        "ix_ml_prediction_review_runs_model_version",
        "prediction_review_runs",
        ["model_version"],
        schema="ml",
    )
    op.create_index(
        "ix_ml_prediction_review_runs_review_status",
        "prediction_review_runs",
        ["review_status"],
        schema="ml",
    )

    op.create_table(
        "prediction_review_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("ml.prediction_review_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("cutoff_at", sa.String(64), nullable=False),
        sa.Column("prediction_date", sa.String(32), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("band", sa.String(32), nullable=True),
        sa.Column("contract_status", sa.String(32), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("record_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_record", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "run_id", "customer_id", "cutoff_at", name="uq_ml_prediction_review_key"
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_ml_prediction_review_score",
        ),
        schema="ml",
    )
    op.create_index(
        "ix_ml_prediction_review_records_run_id",
        "prediction_review_records",
        ["run_id"],
        schema="ml",
    )
    op.create_index(
        "ix_ml_prediction_review_records_customer_id",
        "prediction_review_records",
        ["customer_id"],
        schema="ml",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0024 requires PostgreSQL.")
    op.drop_table("prediction_review_records", schema="ml")
    op.drop_table("prediction_review_runs", schema="ml")
    op.drop_constraint(
        "fk_campaign_execution_job", "campaigns", schema="act", type_="foreignkey"
    )
    op.drop_column("campaigns", "execution_job_id", schema="act")
