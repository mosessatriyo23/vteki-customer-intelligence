import sqlalchemy as sa
from alembic import op

revision = "0008_workflow_correlation_ids"
down_revision = "0007_pipeline_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        schema="act",
    )
    op.create_index(
        "ix_act_campaigns_correlation_id",
        "campaigns",
        ["correlation_id"],
        schema="act",
    )
    op.add_column(
        "identity_reviews",
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        schema="core",
    )
    op.create_index(
        "ix_core_identity_reviews_correlation_id",
        "identity_reviews",
        ["correlation_id"],
        schema="core",
    )
    op.add_column(
        "nba_decisions",
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        schema="dec",
    )
    op.create_index(
        "ix_dec_nba_decisions_correlation_id",
        "nba_decisions",
        ["correlation_id"],
        schema="dec",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dec_nba_decisions_correlation_id",
        table_name="nba_decisions",
        schema="dec",
    )
    op.drop_column("nba_decisions", "correlation_id", schema="dec")
    op.drop_index(
        "ix_core_identity_reviews_correlation_id",
        table_name="identity_reviews",
        schema="core",
    )
    op.drop_column("identity_reviews", "correlation_id", schema="core")
    op.drop_index(
        "ix_act_campaigns_correlation_id", table_name="campaigns", schema="act"
    )
    op.drop_column("campaigns", "correlation_id", schema="act")
