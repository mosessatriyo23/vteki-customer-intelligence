"""Add worker job lease and recovery timestamps."""

import sqlalchemy as sa
from alembic import op

revision = "0011_worker_job_leases"
down_revision = "0010_james_snapshot_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batch_jobs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        schema="act",
    )
    op.add_column(
        "batch_jobs",
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        schema="act",
    )
    op.create_index(
        "ix_act_batch_jobs_status_lease_until",
        "batch_jobs",
        ["status", "lease_until"],
        schema="act",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_act_batch_jobs_status_lease_until",
        table_name="batch_jobs",
        schema="act",
    )
    op.drop_column("batch_jobs", "lease_until", schema="act")
    op.drop_column("batch_jobs", "started_at", schema="act")
