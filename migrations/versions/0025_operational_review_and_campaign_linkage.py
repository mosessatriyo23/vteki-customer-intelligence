"""Exclude legacy demo rows and link reviewed NBA decisions to safe campaigns."""

import sqlalchemy as sa
from alembic import op

revision = "0025_operational_review_and_campaign_linkage"
down_revision = "0024_moses_prediction_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0025 requires PostgreSQL.")

    op.add_column(
        "customers",
        sa.Column(
            "source_type", sa.String(24), server_default="unknown", nullable=False
        ),
        schema="core",
    )
    op.add_column(
        "customers",
        sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="core",
    )
    op.add_column(
        "customers",
        sa.Column("golden_customer_id", sa.String(36), nullable=True),
        schema="core",
    )
    op.create_foreign_key(
        "fk_customers_golden_customer",
        "customers",
        "golden_customers",
        ["golden_customer_id"],
        ["golden_customer_id"],
        source_schema="core",
        referent_schema="identity",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_customer_golden_id", "customers", ["golden_customer_id"], schema="core"
    )
    op.alter_column(
        "customers", "ltv", existing_type=sa.Float(), nullable=True, schema="core"
    )
    op.alter_column(
        "customers",
        "churn_risk",
        existing_type=sa.String(length=16),
        nullable=True,
        schema="core",
    )
    op.execute(
        sa.text(
            """
            UPDATE core.customers
            SET is_demo = TRUE, source_type = 'demo_seed'
            WHERE (customer_code, email) IN (
                ('CUST-1001', 'budi.santoso@example.com'),
                ('CUST-1002', 'siti.rahma@example.com'),
                ('CUST-1003', 'dewi.l@example.com'),
                ('CUST-1004', 'ahmad.h@example.com'),
                ('CUST-1005', 'reza.p@example.com')
            )
            """
        )
    )

    op.add_column(
        "campaigns",
        sa.Column("nba_decision_id", sa.Integer(), nullable=True),
        schema="act",
    )
    op.add_column(
        "campaigns",
        sa.Column("target_customer_id", sa.Integer(), nullable=True),
        schema="act",
    )
    op.create_foreign_key(
        "fk_campaign_nba_decision",
        "campaigns",
        "nba_decisions",
        ["nba_decision_id"],
        ["id"],
        source_schema="act",
        referent_schema="dec",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_campaign_target_customer",
        "campaigns",
        "customers",
        ["target_customer_id"],
        ["id"],
        source_schema="act",
        referent_schema="core",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_campaign_nba_decision", "campaigns", ["nba_decision_id"], schema="act"
    )

    op.add_column(
        "campaign_measurements",
        sa.Column(
            "source_mode", sa.String(24), server_default="unclassified", nullable=False
        ),
        schema="msr",
    )
    op.create_check_constraint(
        "ck_campaign_measurement_source_mode",
        "campaign_measurements",
        "source_mode IN ('simulated', 'unclassified')",
        schema="msr",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0025 requires PostgreSQL.")
    missing_customer_metrics = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM core.customers "
                "WHERE ltv IS NULL OR churn_risk IS NULL LIMIT 1"
            )
        )
        .first()
    )
    if missing_customer_metrics:
        raise RuntimeError(
            "Cannot downgrade migration 0025 while registered customers have "
            "unknown LTV or churn values; preserve the honest empty values."
        )
    op.drop_constraint(
        "ck_campaign_measurement_source_mode",
        "campaign_measurements",
        schema="msr",
        type_="check",
    )
    op.drop_column("campaign_measurements", "source_mode", schema="msr")
    op.drop_constraint(
        "uq_campaign_nba_decision", "campaigns", schema="act", type_="unique"
    )
    op.drop_constraint(
        "fk_campaign_target_customer", "campaigns", schema="act", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_campaign_nba_decision", "campaigns", schema="act", type_="foreignkey"
    )
    op.drop_column("campaigns", "target_customer_id", schema="act")
    op.drop_column("campaigns", "nba_decision_id", schema="act")
    op.alter_column(
        "customers",
        "churn_risk",
        existing_type=sa.String(length=16),
        nullable=False,
        schema="core",
    )
    op.alter_column(
        "customers", "ltv", existing_type=sa.Float(), nullable=False, schema="core"
    )
    op.drop_constraint(
        "uq_customer_golden_id", "customers", schema="core", type_="unique"
    )
    op.drop_constraint(
        "fk_customers_golden_customer", "customers", schema="core", type_="foreignkey"
    )
    op.drop_column("customers", "golden_customer_id", schema="core")
    op.drop_column("customers", "is_demo", schema="core")
    op.drop_column("customers", "source_type", schema="core")
