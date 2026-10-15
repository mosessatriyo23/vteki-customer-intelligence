"""James platform hardening: versioned Customer360 and immutable audit history.

Revision ID: 0010_james_snapshot_controls
Revises: 0009_data_contracts_and_persistent_identity
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_james_snapshot_controls"
down_revision = "0009_data_contracts_and_persistent_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profile_snapshots",
        sa.Column("rule_version", sa.String(length=64), nullable=True),
        schema="customer360",
    )
    op.execute(
        "UPDATE customer360.profile_snapshots "
        "SET rule_version = 'c360-development-v1' WHERE rule_version IS NULL"
    )
    # Explicit duplicate check before replacing the unique constraint.
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM customer360.profile_snapshots "
                "GROUP BY golden_customer_id, cutoff_at, identity_registry_version, rule_version "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate:
        raise RuntimeError(
            "Historical Customer360 duplicates must be reconciled before migration 0010"
        )
    with op.batch_alter_table("profile_snapshots", schema="customer360") as batch:
        batch.alter_column("rule_version", existing_type=sa.String(64), nullable=False)
        batch.drop_constraint("uq_c360_profile_snapshot", type_="unique")
        batch.create_unique_constraint(
            "uq_c360_profile_snapshot",
            [
                "golden_customer_id",
                "cutoff_at",
                "identity_registry_version",
                "rule_version",
            ],
        )

    if op.get_bind().dialect.name == "postgresql":
        # CSV v2 uses UUID36 for CRM IDs. Revision 0009 incorrectly used VARCHAR(32).
        for table, column in (
            ("crm_customers", "crm_customer_id"),
            ("transactions", "source_customer_ref"),
            ("app_events", "source_customer_id"),
            ("service_cases", "source_customer_ref"),
            ("consent_events", "source_customer_ref"),
            ("membership_events", "source_customer_ref"),
            ("customer_visits", "source_customer_ref"),
        ):
            op.execute(
                f"ALTER TABLE source.{table} ALTER COLUMN {column} TYPE VARCHAR(64)"
            )

        # Two append-only audit tables. Triggers also protect against privileged
        # API/worker mistakes; DB owner/superuser can still alter/drop triggers.
        op.execute(
            """CREATE OR REPLACE FUNCTION gov.reject_audit_mutation() RETURNS trigger
               LANGUAGE plpgsql AS $$ BEGIN
                 RAISE EXCEPTION 'Audit history is append-only';
               END $$"""
        )
        for schema, table in (("gov", "audit_event"), ("identity", "review_audit_log")):
            op.execute(
                f"CREATE TRIGGER enforce_append_only BEFORE UPDATE OR DELETE "
                f"ON {schema}.{table} FOR EACH ROW EXECUTE FUNCTION gov.reject_audit_mutation()"
            )
        op.create_check_constraint(
            "ck_c360_revenue_idr_nonnegative",
            "profile_snapshots",
            "retained_revenue >= 0",
            schema="customer360",
        )
        op.create_check_constraint(
            "ck_seg_revenue_idr_nonnegative",
            "rfm_lifecycle_snapshots",
            "monetary >= 0 AND revenue_90d >= 0",
            schema="segmentation",
        )
        op.create_check_constraint(
            "ck_identity_golden_status",
            "golden_customers",
            "status IN ('PROVISIONAL','REVIEW_REQUIRED','APPROVED','REJECTED')",
            schema="identity",
        )
        op.create_check_constraint(
            "ck_stg_batch_status",
            "ingestion_batches",
            "status IN ('STAGED','PUBLISHED','REJECTED')",
            schema="stg",
        )
        op.create_index(
            "ix_gov_audit_trace_timeline",
            "audit_event",
            ["correlation_id", "occurred_at", "id"],
            schema="gov",
        )
        op.create_index(
            "ix_ident_review_queue_status_created",
            "review_queue",
            ["status", "created_at"],
            schema="identity",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index(
            "ix_ident_review_queue_status_created",
            table_name="review_queue",
            schema="identity",
        )
        op.drop_index(
            "ix_gov_audit_trace_timeline", table_name="audit_event", schema="gov"
        )
        op.drop_constraint(
            "ck_stg_batch_status", "ingestion_batches", schema="stg", type_="check"
        )
        op.drop_constraint(
            "ck_identity_golden_status",
            "golden_customers",
            schema="identity",
            type_="check",
        )
        op.drop_constraint(
            "ck_seg_revenue_idr_nonnegative",
            "rfm_lifecycle_snapshots",
            schema="segmentation",
            type_="check",
        )
        op.drop_constraint(
            "ck_c360_revenue_idr_nonnegative",
            "profile_snapshots",
            schema="customer360",
            type_="check",
        )
        for schema, table in (("identity", "review_audit_log"), ("gov", "audit_event")):
            op.execute(f"DROP TRIGGER enforce_append_only ON {schema}.{table}")
        op.execute("DROP FUNCTION gov.reject_audit_mutation()")
        # VARCHAR(64) CRM IDs cannot safely be reduced: downgrade intentionally
        # leaves widened source columns intact to avoid truncating published IDs.
    with op.batch_alter_table("profile_snapshots", schema="customer360") as batch:
        batch.drop_constraint("uq_c360_profile_snapshot", type_="unique")
        batch.create_unique_constraint(
            "uq_c360_profile_snapshot",
            [
                "golden_customer_id",
                "cutoff_at",
                "identity_registry_version",
                "source_batch_id",
            ],
        )
        batch.drop_column("rule_version")
