"""PostgreSQL persistence for Ingestion v2, Identity Registry v1.1, Customer360, and Segmentation.

Revision ID: 0009_data_contracts_and_persistent_identity
Revises: 0008_workflow_correlation_ids
Create Date: 2026-10-14 23:45:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_data_contracts_and_persistent_identity"
down_revision = "0008_workflow_correlation_ids"
branch_labels = None
depends_on = None

NEW_SCHEMAS = ("stg", "source", "identity", "customer360", "segmentation")


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE alembic_version "
            "ALTER COLUMN version_num TYPE VARCHAR(255)"
        )

    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # 1. Ensure schemas exist on PostgreSQL
    if is_pg:
        for schema in NEW_SCHEMAS:
            op.execute(sa.schema.CreateSchema(schema, if_not_exists=True))

    # 2. Schema stg: Ingestion batches and raw landing
    op.create_table(
        "ingestion_batches",
        sa.Column("batch_id", sa.String(length=64), primary_key=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("manifest_payload", sa.JSON(), nullable=False),
        sa.Column("table_checksums", sa.JSON(), nullable=False),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="STAGED"
        ),
        sa.Column("rejection_reasons", sa.JSON(), nullable=True),
        sa.Column("row_counts", sa.JSON(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        schema="stg",
    )
    op.create_index(
        "ix_stg_batches_status", "ingestion_batches", ["status"], schema="stg"
    )

    op.create_table(
        "ingestion_raw_rows",
        sa.Column(
            "batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("table_name", sa.String(length=64), primary_key=True),
        sa.Column("source_id", sa.String(length=64), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="stg",
    )
    op.create_index(
        "ix_stg_raw_table_source",
        "ingestion_raw_rows",
        ["table_name", "source_id"],
        schema="stg",
    )

    # 3. Schema source: Normalized operational tables
    op.create_table(
        "branches",
        sa.Column("branch_code", sa.String(length=16), primary_key=True),
        sa.Column("branch_name", sa.String(length=128), nullable=False),
        sa.Column("city", sa.String(length=64), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("active_flag", sa.Boolean(), nullable=False),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="source",
    )

    op.create_table(
        "catalogue_items",
        sa.Column("item_code", sa.String(length=32), primary_key=True),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("subcategory", sa.String(length=64), nullable=False),
        sa.Column("list_price", sa.BigInteger(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("availability_flag", sa.Boolean(), nullable=False),
        sa.Column("suitability_flags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("approved_facts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="source",
    )

    op.create_table(
        "crm_customers",
        sa.Column("crm_customer_id", sa.String(length=32), primary_key=True),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("phone_raw", sa.String(length=64), nullable=True),
        sa.Column("email_raw", sa.String(length=320), nullable=True),
        sa.Column("birth_month", sa.SmallInteger(), nullable=False),
        sa.Column("gender", sa.String(length=1), nullable=False),
        sa.Column("city", sa.String(length=64), nullable=False),
        sa.Column("member_code", sa.String(length=32), nullable=True),
        sa.Column("membership_tier", sa.String(length=16), nullable=True),
        sa.Column("join_date", sa.Date(), nullable=False),
        sa.Column(
            "preferred_branch_code",
            sa.String(length=16),
            sa.ForeignKey("source.branches.branch_code"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="source",
    )
    op.create_index(
        "ix_source_crm_email", "crm_customers", ["email_raw"], schema="source"
    )
    op.create_index(
        "ix_source_crm_phone", "crm_customers", ["phone_raw"], schema="source"
    )
    op.create_index(
        "ix_source_crm_member", "crm_customers", ["member_code"], schema="source"
    )

    op.create_table(
        "transactions",
        sa.Column("source_transaction_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_customer_ref",
            sa.String(length=32),
            sa.ForeignKey("source.crm_customers.crm_customer_id"),
            nullable=True,
        ),
        sa.Column("source_system", sa.String(length=16), nullable=False),
        sa.Column(
            "branch_code",
            sa.String(length=16),
            sa.ForeignKey("source.branches.branch_code"),
            nullable=True,
        ),
        sa.Column("channel_code", sa.String(length=16), nullable=False),
        sa.Column("transaction_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gross_amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "discount_amount", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("net_amount", sa.BigInteger(), nullable=False),
        sa.Column("refund_amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("actual_revenue", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="source",
    )
    op.create_index(
        "ix_source_trans_customer",
        "transactions",
        ["source_customer_ref"],
        schema="source",
    )
    op.create_index(
        "ix_source_trans_datetime",
        "transactions",
        ["transaction_datetime"],
        schema="source",
    )

    op.create_table(
        "transaction_items",
        sa.Column("source_item_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_transaction_id",
            sa.String(length=64),
            sa.ForeignKey(
                "source.transactions.source_transaction_id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column(
            "item_code",
            sa.String(length=32),
            sa.ForeignKey("source.catalogue_items.item_code"),
            nullable=False,
        ),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.BigInteger(), nullable=False),
        sa.Column("line_amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="source",
    )
    op.create_index(
        "ix_source_item_trans",
        "transaction_items",
        ["source_transaction_id"],
        schema="source",
    )

    op.create_table(
        "app_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_customer_id",
            sa.String(length=32),
            sa.ForeignKey("source.crm_customers.crm_customer_id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column(
            "item_id",
            sa.String(length=32),
            sa.ForeignKey("source.catalogue_items.item_code"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="source",
    )
    op.create_index(
        "ix_source_app_cust_occurred",
        "app_events",
        ["source_customer_id", "occurred_at"],
        schema="source",
    )

    op.create_table(
        "service_cases",
        sa.Column("source_case_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_customer_ref",
            sa.String(length=32),
            sa.ForeignKey("source.crm_customers.crm_customer_id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_code", sa.String(length=64), nullable=True),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="source",
    )

    op.create_table(
        "consent_events",
        sa.Column("source_consent_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_customer_ref",
            sa.String(length=32),
            sa.ForeignKey("source.crm_customers.crm_customer_id"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("channel_code", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capture_source", sa.String(length=64), nullable=False),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="source",
    )

    op.create_table(
        "membership_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_customer_ref",
            sa.String(length=32),
            sa.ForeignKey("source.crm_customers.crm_customer_id"),
            nullable=False,
        ),
        sa.Column("member_code", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("membership_tier", sa.String(length=16), nullable=False),
        sa.Column(
            "previous_event_id",
            sa.String(length=64),
            sa.ForeignKey(
                "source.membership_events.event_id",
                deferrable=True,
                initially="DEFERRED",
            ),
            nullable=True,
        ),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="source",
    )

    op.create_table(
        "customer_visits",
        sa.Column("visit_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_customer_ref",
            sa.String(length=32),
            sa.ForeignKey("source.crm_customers.crm_customer_id"),
            nullable=False,
        ),
        sa.Column(
            "source_transaction_id",
            sa.String(length=64),
            sa.ForeignKey("source.transactions.source_transaction_id"),
            nullable=False,
        ),
        sa.Column(
            "branch_code",
            sa.String(length=16),
            sa.ForeignKey("source.branches.branch_code"),
            nullable=False,
        ),
        sa.Column("visit_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="source",
    )

    # 4. Schema identity: Persistent Golden Registry, Decisions, Reviews
    op.create_table(
        "registry_versions",
        sa.Column("version_tag", sa.String(length=64), primary_key=True),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="ACTIVE"
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="identity",
    )

    op.create_table(
        "golden_customers",
        sa.Column("golden_customer_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "first_source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("anchor_source_id", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="PROVISIONAL"
        ),
        sa.Column("merged_into_golden_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="identity",
    )
    op.create_index(
        "ix_identity_golden_status", "golden_customers", ["status"], schema="identity"
    )

    op.create_table(
        "source_identity_mapping",
        sa.Column("source_customer_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "golden_customer_id",
            sa.String(length=36),
            sa.ForeignKey("identity.golden_customers.golden_customer_id"),
            nullable=False,
        ),
        sa.Column(
            "registry_version",
            sa.String(length=64),
            sa.ForeignKey("identity.registry_versions.version_tag"),
            nullable=False,
        ),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("assignment_type", sa.String(length=24), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        schema="identity",
    )
    op.create_index(
        "ix_identity_mapping_golden",
        "source_identity_mapping",
        ["golden_customer_id"],
        schema="identity",
    )

    op.create_table(
        "match_decisions",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column(
            "registry_version",
            sa.String(length=64),
            sa.ForeignKey("identity.registry_versions.version_tag"),
            nullable=False,
        ),
        sa.Column("left_source_id", sa.String(length=64), nullable=False),
        sa.Column("right_source_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("heuristic_score", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_batch_id",
            "left_source_id",
            "right_source_id",
            name="uq_ident_match_decision_pair",
        ),
        schema="identity",
    )
    op.create_index(
        "ix_identity_decisions_pair",
        "match_decisions",
        ["left_source_id", "right_source_id"],
        schema="identity",
    )

    op.create_table(
        "review_queue",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column(
            "registry_version",
            sa.String(length=64),
            sa.ForeignKey("identity.registry_versions.version_tag"),
            nullable=False,
        ),
        sa.Column("left_source_id", sa.String(length=64), nullable=False),
        sa.Column("right_source_id", sa.String(length=64), nullable=False),
        sa.Column(
            "left_golden_id",
            sa.String(length=36),
            sa.ForeignKey("identity.golden_customers.golden_customer_id"),
            nullable=True,
        ),
        sa.Column(
            "right_golden_id",
            sa.String(length=36),
            sa.ForeignKey("identity.golden_customers.golden_customer_id"),
            nullable=True,
        ),
        sa.Column("heuristic_score", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="PENDING"
        ),
        sa.Column(
            "reviewer_id", sa.Integer(), sa.ForeignKey("core.users.id"), nullable=True
        ),
        sa.Column("reviewer_note", sa.String(length=1000), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "registry_version",
            "left_source_id",
            "right_source_id",
            name="uq_ident_review_queue_pair",
        ),
        schema="identity",
    )
    op.create_index(
        "ix_identity_review_status", "review_queue", ["status"], schema="identity"
    )

    op.create_table(
        "review_audit_log",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "review_queue_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("identity.review_queue.id"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", sa.Integer(), sa.ForeignKey("core.users.id"), nullable=False
        ),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("previous_golden_id", sa.String(length=36), nullable=True),
        sa.Column("new_golden_id", sa.String(length=36), nullable=True),
        sa.Column("rationale", sa.String(length=1000), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        schema="identity",
    )
    op.create_index(
        "ix_identity_audit_queue",
        "review_audit_log",
        ["review_queue_id"],
        schema="identity",
    )
    op.create_index(
        "ix_identity_audit_corr",
        "review_audit_log",
        ["correlation_id"],
        schema="identity",
    )

    # 5. Schema customer360: Profile Snapshots
    op.create_table(
        "profile_snapshots",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "golden_customer_id",
            sa.String(length=36),
            sa.ForeignKey("identity.golden_customers.golden_customer_id"),
            nullable=False,
        ),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "identity_registry_version",
            sa.String(length=64),
            sa.ForeignKey("identity.registry_versions.version_tag"),
            nullable=False,
        ),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("identity_status", sa.String(length=24), nullable=False),
        sa.Column("source_identity_count", sa.Integer(), nullable=False),
        sa.Column("first_join_date", sa.Date(), nullable=False),
        sa.Column(
            "transaction_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "retained_revenue", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("last_transaction_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("visit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("renewal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "golden_customer_id",
            "cutoff_at",
            "identity_registry_version",
            "source_batch_id",
            name="uq_c360_profile_snapshot",
        ),
        schema="customer360",
    )
    op.create_index(
        "ix_c360_snapshots_lookup",
        "profile_snapshots",
        ["golden_customer_id", "cutoff_at"],
        schema="customer360",
    )

    # 6. Schema segmentation: RFM & Lifecycle Snapshots
    op.create_table(
        "rfm_lifecycle_snapshots",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "golden_customer_id",
            sa.String(length=36),
            sa.ForeignKey("identity.golden_customers.golden_customer_id"),
            nullable=False,
        ),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "identity_registry_version",
            sa.String(length=64),
            sa.ForeignKey("identity.registry_versions.version_tag"),
            nullable=False,
        ),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("stg.ingestion_batches.batch_id"),
            nullable=False,
        ),
        sa.Column("identity_status", sa.String(length=24), nullable=False),
        sa.Column("recency_days", sa.Integer(), nullable=True),
        sa.Column("frequency", sa.Integer(), nullable=False),
        sa.Column("monetary", sa.BigInteger(), nullable=False),
        sa.Column(
            "rfm_window_days", sa.Integer(), nullable=False, server_default="365"
        ),
        sa.Column("r_score", sa.SmallInteger(), nullable=False),
        sa.Column("f_score", sa.SmallInteger(), nullable=False),
        sa.Column("m_score", sa.SmallInteger(), nullable=False),
        sa.Column("rfm_code", sa.String(length=3), nullable=False),
        sa.Column("tenure_days", sa.Integer(), nullable=False),
        sa.Column("transactions_60d", sa.Integer(), nullable=False),
        sa.Column("transactions_90d", sa.Integer(), nullable=False),
        sa.Column("revenue_90d", sa.BigInteger(), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.UniqueConstraint(
            "golden_customer_id",
            "cutoff_at",
            "identity_registry_version",
            "rule_version",
            name="uq_segmentation_rfm_snapshot",
        ),
        schema="segmentation",
    )
    op.create_index(
        "ix_seg_snapshots_lookup",
        "rfm_lifecycle_snapshots",
        ["golden_customer_id", "cutoff_at"],
        schema="segmentation",
    )
    op.create_index(
        "ix_seg_snapshots_lifecycle",
        "rfm_lifecycle_snapshots",
        ["lifecycle"],
        schema="segmentation",
    )


def downgrade() -> None:
    op.drop_table("rfm_lifecycle_snapshots", schema="segmentation")
    op.drop_table("profile_snapshots", schema="customer360")
    op.drop_table("review_audit_log", schema="identity")
    op.drop_table("review_queue", schema="identity")
    op.drop_table("match_decisions", schema="identity")
    op.drop_table("source_identity_mapping", schema="identity")
    op.drop_table("golden_customers", schema="identity")
    op.drop_table("registry_versions", schema="identity")
    op.drop_table("customer_visits", schema="source")
    op.drop_table("membership_events", schema="source")
    op.drop_table("consent_events", schema="source")
    op.drop_table("service_cases", schema="source")
    op.drop_table("app_events", schema="source")
    op.drop_table("transaction_items", schema="source")
    op.drop_table("transactions", schema="source")
    op.drop_table("crm_customers", schema="source")
    op.drop_table("catalogue_items", schema="source")
    op.drop_table("branches", schema="source")
    op.drop_table("ingestion_raw_rows", schema="stg")
    op.drop_table("ingestion_batches", schema="stg")
