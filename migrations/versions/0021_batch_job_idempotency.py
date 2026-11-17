"""Add an optional idempotency key to batch jobs."""

import sqlalchemy as sa
from alembic import op

revision = "0021_batch_job_idempotency"
down_revision = "0020_business_event_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0021 requires PostgreSQL.")

    op.add_column(
        "batch_jobs",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        schema="act",
    )
    op.create_unique_constraint(
        "uq_batch_jobs_idempotency",
        "batch_jobs",
        ["idempotency_key"],
        schema="act",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0021 requires PostgreSQL.")

    op.drop_constraint(
        "uq_batch_jobs_idempotency",
        "batch_jobs",
        schema="act",
        type_="unique",
    )
    op.drop_column("batch_jobs", "idempotency_key", schema="act")
