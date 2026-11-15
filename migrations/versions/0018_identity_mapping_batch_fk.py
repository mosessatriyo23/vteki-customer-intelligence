"""Add ingestion batch foreign key to identity mapping history."""

import sqlalchemy as sa
from alembic import op

revision = "0018_identity_mapping_batch_fk"
down_revision = "0017_catalogue_batch_versioning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        raise RuntimeError("Migration 0018 requires PostgreSQL.")

    # Refuse migration if existing history contains invalid batch references.
    orphan_count = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM identity.identity_mapping_history AS h
            LEFT JOIN stg.ingestion_batches AS b
              ON b.batch_id = h.source_batch_id
            WHERE b.batch_id IS NULL
            """
        )
    ).scalar_one()

    if orphan_count:
        raise RuntimeError(
            "Cannot add identity mapping batch FK: "
            f"{orphan_count} orphan source_batch_id reference(s) found."
        )

    op.create_foreign_key(
        "fk_identity_mapping_history_source_batch",
        "identity_mapping_history",
        "ingestion_batches",
        ["source_batch_id"],
        ["batch_id"],
        source_schema="identity",
        referent_schema="stg",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0018 requires PostgreSQL.")

    op.drop_constraint(
        "fk_identity_mapping_history_source_batch",
        "identity_mapping_history",
        schema="identity",
        type_="foreignkey",
    )
