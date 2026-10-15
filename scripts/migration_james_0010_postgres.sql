-- PostgreSQL-only SQL equivalent for inspection or manually managed deployments.
-- Preferred deployment: `alembic upgrade head`. DO NOT run both.
-- Prerequisite: revision 0009_data_contracts_and_persistent_identity is applied.
BEGIN;

-- Source customer UUID values have 36 chars; 0009 columns were VARCHAR(32).
ALTER TABLE source.crm_customers ALTER COLUMN crm_customer_id TYPE VARCHAR(64);
ALTER TABLE source.transactions ALTER COLUMN source_customer_ref TYPE VARCHAR(64);
ALTER TABLE source.app_events ALTER COLUMN source_customer_id TYPE VARCHAR(64);
ALTER TABLE source.service_cases ALTER COLUMN source_customer_ref TYPE VARCHAR(64);
ALTER TABLE source.consent_events ALTER COLUMN source_customer_ref TYPE VARCHAR(64);
ALTER TABLE source.membership_events ALTER COLUMN source_customer_ref TYPE VARCHAR(64);
ALTER TABLE source.customer_visits ALTER COLUMN source_customer_ref TYPE VARCHAR(64);

ALTER TABLE customer360.profile_snapshots ADD COLUMN rule_version VARCHAR(64);
UPDATE customer360.profile_snapshots SET rule_version = 'c360-development-v1'
 WHERE rule_version IS NULL;
DO $$ BEGIN
 IF EXISTS (
   SELECT 1 FROM customer360.profile_snapshots
   GROUP BY golden_customer_id, cutoff_at, identity_registry_version, rule_version
   HAVING COUNT(*) > 1
 ) THEN
   RAISE EXCEPTION 'Duplicate Customer360 snapshot keys: reconcile historical rows first';
 END IF;
END $$;
ALTER TABLE customer360.profile_snapshots ALTER COLUMN rule_version SET NOT NULL;
ALTER TABLE customer360.profile_snapshots DROP CONSTRAINT uq_c360_profile_snapshot;
ALTER TABLE customer360.profile_snapshots ADD CONSTRAINT uq_c360_profile_snapshot
 UNIQUE (golden_customer_id, cutoff_at, identity_registry_version, rule_version);

CREATE OR REPLACE FUNCTION gov.reject_audit_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Audit history is append-only'; END $$;
CREATE TRIGGER enforce_append_only BEFORE UPDATE OR DELETE ON gov.audit_event
FOR EACH ROW EXECUTE FUNCTION gov.reject_audit_mutation();
CREATE TRIGGER enforce_append_only BEFORE UPDATE OR DELETE ON identity.review_audit_log
FOR EACH ROW EXECUTE FUNCTION gov.reject_audit_mutation();

ALTER TABLE customer360.profile_snapshots ADD CONSTRAINT ck_c360_revenue_idr_nonnegative
 CHECK (retained_revenue >= 0);
ALTER TABLE segmentation.rfm_lifecycle_snapshots ADD CONSTRAINT ck_seg_revenue_idr_nonnegative
 CHECK (monetary >= 0 AND revenue_90d >= 0);
ALTER TABLE identity.golden_customers ADD CONSTRAINT ck_identity_golden_status
 CHECK (status IN ('PROVISIONAL','REVIEW_REQUIRED','APPROVED','REJECTED'));
ALTER TABLE stg.ingestion_batches ADD CONSTRAINT ck_stg_batch_status
 CHECK (status IN ('STAGED','PUBLISHED','REJECTED'));
CREATE INDEX ix_gov_audit_trace_timeline
 ON gov.audit_event (correlation_id, occurred_at, id);
CREATE INDEX ix_ident_review_queue_status_created
 ON identity.review_queue (status, created_at);
COMMIT;
-- This SQL does not update Alembic's version table. Prefer Alembic for managed DB.
