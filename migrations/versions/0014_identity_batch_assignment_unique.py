"""Prevent duplicate identity batch assignment history events."""

import sqlalchemy as sa
from alembic import op

revision = "0014_identity_batch_assignment_unique"
down_revision = "0013_identity_mapping_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Identity history index migration requires PostgreSQL.")

    op.create_index(
        "uq_identity_mapping_history_batch_assignment",
        "identity_mapping_history",
        [
            "source_customer_id",
            "source_batch_id",
            "registry_version",
            "golden_customer_id",
        ],
        unique=True,
        schema="identity",
        postgresql_where=sa.text("event_type = 'BATCH_ASSIGNMENT'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_identity_mapping_history_batch_assignment",
        table_name="identity_mapping_history",
        schema="identity",
    )
