"""Add claim token to prevent stale worker completion."""

import sqlalchemy as sa
from alembic import op

revision = "0012_worker_job_claim_token"
down_revision = "0011_worker_job_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batch_jobs",
        sa.Column("claim_token", sa.String(length=36), nullable=True),
        schema="act",
    )


def downgrade() -> None:
    op.drop_column("batch_jobs", "claim_token", schema="act")
