"""Add explicit run-level usage decisions without approving existing runs."""

import sqlalchemy as sa
from alembic import op

revision = "0027_prediction_usage_authorization"
down_revision = "0026_campaign_contact_measurement_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0027 requires PostgreSQL.")

    for column in (
        sa.Column("usage_approved", sa.Boolean(), nullable=True),
        sa.Column("usage_decided_by", sa.Integer(), nullable=True),
        sa.Column("usage_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("usage_note", sa.Text(), nullable=True),
        sa.Column("model_author", sa.Integer(), nullable=True),
    ):
        op.add_column("prediction_review_runs", column, schema="ml")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0027 requires PostgreSQL.")

    for name in (
        "model_author",
        "usage_note",
        "usage_decided_at",
        "usage_decided_by",
        "usage_approved",
    ):
        op.drop_column("prediction_review_runs", name, schema="ml")
