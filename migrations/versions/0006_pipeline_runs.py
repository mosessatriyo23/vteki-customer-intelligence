import sqlalchemy as sa
from alembic import op

revision = "0007_pipeline_runs"
down_revision = "0006_governance_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("step_results", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        schema="stg",
    )
    op.create_index(
        "ix_stg_pipeline_runs_status", "pipeline_runs", ["status"], schema="stg"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stg_pipeline_runs_status", table_name="pipeline_runs", schema="stg"
    )
    op.drop_table("pipeline_runs", schema="stg")
