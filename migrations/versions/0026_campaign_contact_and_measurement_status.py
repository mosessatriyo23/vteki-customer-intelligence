"""Persist campaign contact history and honest measurement availability."""

import sqlalchemy as sa
from alembic import op

revision = "0026_campaign_contact_measurement_status"
down_revision = "0025_operational_review_and_campaign_linkage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0026 requires PostgreSQL.")

    op.add_column(
        "campaign_measurements",
        sa.Column("execution_job_id", sa.Integer(), nullable=True),
        schema="msr",
    )
    op.create_foreign_key(
        "fk_campaign_measurement_execution_job",
        "campaign_measurements",
        "batch_jobs",
        ["execution_job_id"],
        ["id"],
        source_schema="msr",
        referent_schema="act",
        ondelete="RESTRICT",
    )
    op.add_column(
        "campaign_measurements",
        sa.Column(
            "measurement_status",
            sa.String(32),
            server_default=sa.text("'LEGACY_RECORDED'"),
            nullable=False,
        ),
        schema="msr",
    )
    op.alter_column(
        "campaign_measurements",
        "observed_value",
        existing_type=sa.Float(),
        nullable=True,
        schema="msr",
    )
    op.alter_column(
        "campaign_measurements",
        "incremental_value",
        existing_type=sa.Float(),
        nullable=True,
        schema="msr",
    )
    op.create_unique_constraint(
        "uq_campaign_measurement_job_metric",
        "campaign_measurements",
        ["execution_job_id", "metric_name"],
        schema="msr",
    )

    op.create_table(
        "campaign_contact_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("execution_job_id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("customer_ref", sa.String(128), nullable=False),
        sa.Column("action_id", sa.String(128), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_commercial", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["execution_job_id"],
            ["act.batch_jobs.id"],
            name="fk_campaign_contact_execution_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["act.campaigns.id"],
            name="fk_campaign_contact_campaign",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["core.customers.id"],
            name="fk_campaign_contact_customer",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "execution_job_id",
            "customer_id",
            name="uq_campaign_contact_job_customer",
        ),
        schema="act",
    )
    op.create_index(
        "ix_act_campaign_contact_history_execution_job_id",
        "campaign_contact_history",
        ["execution_job_id"],
        schema="act",
    )
    op.create_index(
        "ix_act_campaign_contact_history_campaign_id",
        "campaign_contact_history",
        ["campaign_id"],
        schema="act",
    )
    op.create_index(
        "ix_act_campaign_contact_history_customer_id",
        "campaign_contact_history",
        ["customer_id"],
        schema="act",
    )
    op.create_index(
        "ix_act_campaign_contact_history_customer_ref",
        "campaign_contact_history",
        ["customer_ref"],
        schema="act",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0026 requires PostgreSQL.")

    op.drop_table("campaign_contact_history", schema="act")
    op.drop_constraint(
        "uq_campaign_measurement_job_metric",
        "campaign_measurements",
        schema="msr",
        type_="unique",
    )
    op.alter_column(
        "campaign_measurements",
        "observed_value",
        existing_type=sa.Float(),
        nullable=False,
        schema="msr",
    )
    op.alter_column(
        "campaign_measurements",
        "incremental_value",
        existing_type=sa.Float(),
        nullable=False,
        schema="msr",
    )
    op.drop_column("campaign_measurements", "measurement_status", schema="msr")
    op.drop_constraint(
        "fk_campaign_measurement_execution_job",
        "campaign_measurements",
        schema="msr",
        type_="foreignkey",
    )
    op.drop_column("campaign_measurements", "execution_job_id", schema="msr")
