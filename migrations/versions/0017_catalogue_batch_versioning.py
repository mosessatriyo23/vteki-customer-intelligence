"""Version catalogue items by ingestion batch."""

import sqlalchemy as sa
from alembic import op

revision = "0017_catalogue_batch_versioning"
down_revision = "0016_transaction_event_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0017 requires PostgreSQL.")

    # Existing data must already belong to the same batch as its references.
    mismatch = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT COUNT(*)
            FROM source.transaction_items ti
            JOIN source.catalogue_items ci
              ON ci.item_code = ti.item_code
            WHERE ti.source_batch_id <> ci.source_batch_id
            """
            )
        )
        .scalar_one()
    )

    if mismatch:
        raise RuntimeError(
            "Cannot version catalogue: transaction_items batch mismatch."
        )

    mismatch = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT COUNT(*)
            FROM source.app_events ae
            JOIN source.catalogue_items ci
              ON ci.item_code = ae.item_id
            WHERE ae.item_id IS NOT NULL
              AND ae.source_batch_id <> ci.source_batch_id
            """
            )
        )
        .scalar_one()
    )

    if mismatch:
        raise RuntimeError("Cannot version catalogue: app_events batch mismatch.")

    op.drop_constraint(
        "transaction_items_item_code_fkey",
        "transaction_items",
        schema="source",
        type_="foreignkey",
    )
    op.drop_constraint(
        "app_events_item_id_fkey",
        "app_events",
        schema="source",
        type_="foreignkey",
    )
    op.drop_constraint(
        "catalogue_items_pkey",
        "catalogue_items",
        schema="source",
        type_="primary",
    )

    op.create_primary_key(
        "catalogue_items_pkey",
        "catalogue_items",
        ["item_code", "source_batch_id"],
        schema="source",
    )

    op.create_foreign_key(
        "fk_transaction_items_catalogue_batch",
        "transaction_items",
        "catalogue_items",
        ["item_code", "source_batch_id"],
        ["item_code", "source_batch_id"],
        source_schema="source",
        referent_schema="source",
    )

    op.create_foreign_key(
        "fk_app_events_catalogue_batch",
        "app_events",
        "catalogue_items",
        ["item_id", "source_batch_id"],
        ["item_code", "source_batch_id"],
        source_schema="source",
        referent_schema="source",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Migration 0017 requires PostgreSQL.")

    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT COUNT(*)
            FROM (
                SELECT item_code
                FROM source.catalogue_items
                GROUP BY item_code
                HAVING COUNT(*) > 1
            ) AS duplicated_items
            """
            )
        )
        .scalar_one()
    )

    if duplicates:
        raise RuntimeError("Cannot downgrade: multiple catalogue versions exist.")

    op.drop_constraint(
        "fk_transaction_items_catalogue_batch",
        "transaction_items",
        schema="source",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_app_events_catalogue_batch",
        "app_events",
        schema="source",
        type_="foreignkey",
    )
    op.drop_constraint(
        "catalogue_items_pkey",
        "catalogue_items",
        schema="source",
        type_="primary",
    )

    op.create_primary_key(
        "catalogue_items_pkey",
        "catalogue_items",
        ["item_code"],
        schema="source",
    )

    op.create_foreign_key(
        "transaction_items_item_code_fkey",
        "transaction_items",
        "catalogue_items",
        ["item_code"],
        ["item_code"],
        source_schema="source",
        referent_schema="source",
    )

    op.create_foreign_key(
        "app_events_item_id_fkey",
        "app_events",
        "catalogue_items",
        ["item_id"],
        ["item_code"],
        source_schema="source",
        referent_schema="source",
    )
