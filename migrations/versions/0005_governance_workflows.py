import sqlalchemy as sa
from alembic import op

revision = "0006_governance_workflows"
down_revision = "0005_governance_schemas_and_traceability"
branch_labels = None
depends_on = None


SCHEMAS = ("core", "stg", "feat", "ml", "dec", "act", "msr", "gov")


def _move(table: str, schema: str) -> None:
    op.execute(sa.text(f'ALTER TABLE public."{table}" SET SCHEMA "{schema}"'))


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(sa.schema.CreateSchema(schema, if_not_exists=True))

    for table, schema in (
        ("roles", "core"),
        ("users", "core"),
        ("user_roles", "core"),
        ("customers", "core"),
        ("campaigns", "act"),
        ("batch_jobs", "act"),
        ("audit_events", "gov"),
        ("identity_reviews", "core"),
        ("human_overrides", "dec"),
        ("model_drift_logs", "ml"),
        ("decision_traces", "gov"),
    ):
        _move(table, schema)

    for old, new in (
        ("ix_roles_name", "ix_core_roles_name"),
        ("ix_users_email", "ix_core_users_email"),
        ("ix_customers_customer_code", "ix_core_customers_customer_code"),
        ("ix_customers_segment", "ix_core_customers_segment"),
        ("ix_audit_events_request_id", "ix_gov_audit_event_request_id"),
        ("ix_audit_events_correlation_id", "ix_gov_audit_event_correlation_id"),
        ("ix_identity_reviews_status", "ix_core_identity_reviews_status"),
        ("ix_human_overrides_customer_id", "ix_dec_human_overrides_customer_id"),
        ("ix_decision_traces_correlation_id", "ix_gov_decision_traces_correlation_id"),
        ("ix_decision_traces_customer_code", "ix_gov_decision_traces_customer_code"),
    ):
        schema = new.split("_", 2)[1]
        op.execute(sa.text(f'ALTER INDEX "{schema}"."{old}" RENAME TO "{new}"'))

    op.execute("ALTER TABLE gov.audit_events RENAME TO audit_event")
    op.alter_column(
        "audit_event",
        "correlation_id",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        schema="gov",
    )
    op.execute(
        "UPDATE gov.audit_event SET correlation_id = request_id WHERE correlation_id IS NULL"
    )
    op.alter_column("audit_event", "correlation_id", nullable=False, schema="gov")
    op.add_column(
        "audit_event",
        sa.Column(
            "event_type",
            sa.String(length=64),
            server_default="http.request",
            nullable=False,
        ),
        schema="gov",
    )
    op.add_column(
        "audit_event",
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        schema="gov",
    )
    op.add_column(
        "audit_event",
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        schema="gov",
    )
    op.add_column(
        "audit_event",
        sa.Column(
            "details", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False
        ),
        schema="gov",
    )

    op.add_column(
        "identity_reviews",
        sa.Column(
            "subject_reference",
            sa.String(length=128),
            server_default="",
            nullable=False,
        ),
        schema="core",
    )
    op.execute(
        "UPDATE core.identity_reviews SET subject_reference = customer_code, status = lower(status)"
    )
    op.alter_column(
        "identity_reviews", "status", server_default="pending", schema="core"
    )
    op.alter_column(
        "identity_reviews", "subject_reference", server_default=None, schema="core"
    )
    op.add_column(
        "identity_reviews",
        sa.Column(
            "candidate_references",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        schema="core",
    )
    op.add_column(
        "identity_reviews",
        sa.Column("confidence", sa.Float(), server_default="0", nullable=False),
        schema="core",
    )
    op.execute(
        "UPDATE core.identity_reviews SET confidence = match_confidence, "
        "candidate_references = json_build_array(customer_code)"
    )
    op.add_column(
        "identity_reviews",
        sa.Column("decision", sa.String(length=24), nullable=True),
        schema="core",
    )
    op.add_column(
        "identity_reviews",
        sa.Column("review_note", sa.String(length=1000), nullable=True),
        schema="core",
    )
    op.add_column(
        "identity_reviews",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.create_index(
        "ix_core_identity_reviews_subject_reference",
        "identity_reviews",
        ["subject_reference"],
        schema="core",
    )

    op.execute("ALTER TABLE ml.model_drift_logs RENAME TO model_drift_metrics")
    op.alter_column(
        "model_drift_metrics", "psi_score", new_column_name="metric_value", schema="ml"
    )
    op.alter_column(
        "model_drift_metrics", "drift_status", new_column_name="status", schema="ml"
    )
    op.alter_column(
        "model_drift_metrics", "checked_at", new_column_name="measured_at", schema="ml"
    )
    op.add_column(
        "model_drift_metrics",
        sa.Column(
            "metric_name", sa.String(length=100), server_default="psi", nullable=False
        ),
        schema="ml",
    )
    op.add_column(
        "model_drift_metrics",
        sa.Column("threshold", sa.Float(), server_default="0.2", nullable=False),
        schema="ml",
    )
    op.alter_column(
        "model_drift_metrics", "metric_name", server_default=None, schema="ml"
    )
    op.alter_column(
        "model_drift_metrics", "threshold", server_default=None, schema="ml"
    )
    op.create_index(
        "ix_ml_model_drift_metrics_model_name",
        "model_drift_metrics",
        ["model_name"],
        schema="ml",
    )
    op.create_index(
        "ix_ml_model_drift_metrics_status",
        "model_drift_metrics",
        ["status"],
        schema="ml",
    )

    op.alter_column(
        "decision_traces",
        "correlation_id",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        schema="gov",
    )
    op.add_column(
        "campaigns",
        sa.Column("message_draft", sa.String(length=2000), nullable=True),
        schema="act",
    )
    op.add_column(
        "campaigns", sa.Column("approved_by", sa.Integer(), nullable=True), schema="act"
    )
    op.add_column(
        "campaigns",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        schema="act",
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("records_seen", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        schema="stg",
    )
    op.create_index(
        "ix_stg_ingestion_runs_status", "ingestion_runs", ["status"], schema="stg"
    )
    op.create_table(
        "customer_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("feature_name", sa.String(length=100), nullable=False),
        sa.Column("feature_value", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["core.customers.id"], ondelete="CASCADE"
        ),
        schema="feat",
    )
    op.create_index(
        "ix_feat_customer_features_customer_id",
        "customer_features",
        ["customer_id"],
        schema="feat",
    )
    op.create_table(
        "nba_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("recommended_action", sa.String(length=256), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("selected_action", sa.String(length=256), nullable=True),
        sa.Column("overridden_by", sa.Integer(), nullable=True),
        sa.Column("override_reason", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["core.customers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["overridden_by"], ["core.users.id"]),
        schema="dec",
    )
    op.create_index(
        "ix_dec_nba_decisions_customer_id",
        "nba_decisions",
        ["customer_id"],
        schema="dec",
    )
    op.create_index(
        "ix_dec_nba_decisions_status", "nba_decisions", ["status"], schema="dec"
    )
    op.create_table(
        "campaign_measurements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("incremental_value", sa.Float(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["act.campaigns.id"], ondelete="CASCADE"
        ),
        schema="msr",
    )
    op.create_index(
        "ix_msr_campaign_measurements_campaign_id",
        "campaign_measurements",
        ["campaign_id"],
        schema="msr",
    )
    op.execute(
        """
        CREATE FUNCTION gov.reject_audit_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'gov.audit_event is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_event_append_only
        BEFORE UPDATE OR DELETE ON gov.audit_event
        FOR EACH ROW EXECUTE FUNCTION gov.reject_audit_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_event_append_only ON gov.audit_event")
    op.execute("DROP FUNCTION IF EXISTS gov.reject_audit_mutation()")
    op.drop_table("campaign_measurements", schema="msr")
    op.drop_table("nba_decisions", schema="dec")
    op.drop_table("customer_features", schema="feat")
    op.drop_index(
        "ix_stg_ingestion_runs_status", table_name="ingestion_runs", schema="stg"
    )
    op.drop_table("ingestion_runs", schema="stg")
    op.drop_column("campaigns", "approved_at", schema="act")
    op.drop_column("campaigns", "approved_by", schema="act")
    op.drop_column("campaigns", "message_draft", schema="act")
    op.drop_index(
        "ix_ml_model_drift_metrics_status",
        table_name="model_drift_metrics",
        schema="ml",
    )
    op.drop_index(
        "ix_ml_model_drift_metrics_model_name",
        table_name="model_drift_metrics",
        schema="ml",
    )
    op.drop_column("model_drift_metrics", "threshold", schema="ml")
    op.drop_column("model_drift_metrics", "metric_name", schema="ml")
    op.alter_column(
        "model_drift_metrics", "measured_at", new_column_name="checked_at", schema="ml"
    )
    op.alter_column(
        "model_drift_metrics", "status", new_column_name="drift_status", schema="ml"
    )
    op.alter_column(
        "model_drift_metrics", "metric_value", new_column_name="psi_score", schema="ml"
    )
    op.execute("ALTER TABLE ml.model_drift_metrics RENAME TO model_drift_logs")
    op.alter_column(
        "decision_traces",
        "correlation_id",
        existing_type=sa.String(128),
        type_=sa.String(64),
        schema="gov",
    )
    op.drop_index(
        "ix_core_identity_reviews_subject_reference",
        table_name="identity_reviews",
        schema="core",
    )
    for column in (
        "reviewed_at",
        "review_note",
        "decision",
        "confidence",
        "candidate_references",
        "subject_reference",
    ):
        op.drop_column("identity_reviews", column, schema="core")
    op.execute("UPDATE core.identity_reviews SET status = initcap(status)")
    op.drop_column("audit_event", "details", schema="gov")
    op.drop_column("audit_event", "entity_id", schema="gov")
    op.drop_column("audit_event", "entity_type", schema="gov")
    op.drop_column("audit_event", "event_type", schema="gov")
    op.alter_column(
        "audit_event",
        "correlation_id",
        existing_type=sa.String(128),
        type_=sa.String(64),
        schema="gov",
    )
    op.execute("ALTER TABLE gov.audit_event RENAME TO audit_events")

    for table, schema in (
        ("decision_traces", "gov"),
        ("human_overrides", "dec"),
        ("identity_reviews", "core"),
        ("audit_events", "gov"),
        ("batch_jobs", "act"),
        ("campaigns", "act"),
        ("customers", "core"),
        ("user_roles", "core"),
        ("users", "core"),
        ("roles", "core"),
    ):
        op.execute(sa.text(f'ALTER TABLE "{schema}"."{table}" SET SCHEMA public'))
    for schema, old, new in (
        ("public", "ix_core_roles_name", "ix_roles_name"),
        ("public", "ix_core_users_email", "ix_users_email"),
        ("public", "ix_core_customers_customer_code", "ix_customers_customer_code"),
        ("public", "ix_core_customers_segment", "ix_customers_segment"),
        ("public", "ix_core_identity_reviews_status", "ix_identity_reviews_status"),
        (
            "public",
            "ix_dec_human_overrides_customer_id",
            "ix_human_overrides_customer_id",
        ),
        (
            "public",
            "ix_gov_decision_traces_correlation_id",
            "ix_decision_traces_correlation_id",
        ),
        (
            "public",
            "ix_gov_decision_traces_customer_code",
            "ix_decision_traces_customer_code",
        ),
        ("public", "ix_gov_audit_event_request_id", "ix_audit_events_request_id"),
        (
            "public",
            "ix_gov_audit_event_correlation_id",
            "ix_audit_events_correlation_id",
        ),
    ):
        op.execute(sa.text(f'ALTER INDEX "{old}" RENAME TO "{new}"'))
