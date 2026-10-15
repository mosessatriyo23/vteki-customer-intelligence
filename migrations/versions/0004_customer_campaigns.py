import sqlalchemy as sa
from alembic import op

revision = "0004_customer_campaigns"
down_revision = "0003_batch_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(length=32), nullable=False),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("segment", sa.String(length=64), nullable=False),
        sa.Column("ltv", sa.Float(), nullable=False),
        sa.Column("churn_risk", sa.String(length=16), nullable=False),
        sa.Column("next_best_action", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_code", name="uq_customers_customer_code"),
    )
    op.create_index("ix_customers_customer_code", "customers", ["customer_code"])
    op.create_index("ix_customers_segment", "customers", ["segment"])
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("target_segment", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("ab_test_ratio", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("campaigns")
    op.drop_index("ix_customers_segment", table_name="customers")
    op.drop_index("ix_customers_customer_code", table_name="customers")
    op.drop_table("customers")
