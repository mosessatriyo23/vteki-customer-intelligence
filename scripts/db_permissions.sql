-- ============================================================================
-- POSTGRESQL PERMISSIONS & ROLE ISOLATION (RBAC)
-- Database: vteki_intelligence
-- ============================================================================

-- 1. Create Roles
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vteki_migrator') THEN
        CREATE ROLE vteki_migrator WITH LOGIN PASSWORD 'vteki_migrator_secure_pass';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vteki_ingestion_writer') THEN
        CREATE ROLE vteki_ingestion_writer WITH LOGIN PASSWORD 'vteki_writer_secure_pass';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vteki_identity_reviewer') THEN
        CREATE ROLE vteki_identity_reviewer WITH LOGIN PASSWORD 'vteki_reviewer_secure_pass';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vteki_serving_reader') THEN
        CREATE ROLE vteki_serving_reader WITH LOGIN PASSWORD 'vteki_reader_secure_pass';
    END IF;
END $$;

-- 2. Migrator (DDL Owner)
GRANT ALL PRIVILEGES ON ALL SCHEMAS IN DATABASE vteki_intelligence TO vteki_migrator;
ALTER DEFAULT PRIVILEGES IN SCHEMA stg, source, identity, customer360, segmentation, core, gov, act, feat, ml, dec, msr
    GRANT ALL ON TABLES TO vteki_migrator;

-- 3. Ingestion Writer Role
-- Allowed schemas for pipeline worker
GRANT USAGE ON SCHEMA stg, source, identity, customer360, segmentation TO vteki_ingestion_writer;

-- Staging & Raw
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA stg TO vteki_ingestion_writer;

-- Normalized Source
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA source TO vteki_ingestion_writer;

-- Identity Registry
GRANT SELECT, INSERT, UPDATE ON identity.golden_customers TO vteki_ingestion_writer;
GRANT SELECT, INSERT, UPDATE ON identity.source_identity_mapping TO vteki_ingestion_writer;
GRANT SELECT, INSERT ON identity.match_decisions TO vteki_ingestion_writer;
GRANT SELECT, INSERT ON identity.review_queue TO vteki_ingestion_writer;
GRANT SELECT ON identity.registry_versions TO vteki_ingestion_writer;

-- Snapshots
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA customer360 TO vteki_ingestion_writer;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA segmentation TO vteki_ingestion_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA stg, source, identity, customer360, segmentation TO vteki_ingestion_writer;

-- ISOLATION: Explicitly block access to any evaluation / ground truth schema
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.schemata WHERE schema_name = 'evaluation') THEN
        REVOKE ALL ON SCHEMA evaluation FROM vteki_ingestion_writer;
    END IF;
END $$;

-- 4. Identity Reviewer Role (Governance UI / Reviewer API)
GRANT USAGE ON SCHEMA identity, gov, core TO vteki_identity_reviewer;
GRANT SELECT ON identity.golden_customers, identity.source_identity_mapping, identity.match_decisions TO vteki_identity_reviewer;
GRANT SELECT, UPDATE (status, reviewer_id, reviewer_note, decided_at) ON identity.review_queue TO vteki_identity_reviewer;
GRANT SELECT, INSERT ON identity.review_audit_log TO vteki_identity_reviewer;
GRANT SELECT, INSERT ON gov.audit_event TO vteki_identity_reviewer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA identity TO vteki_identity_reviewer;

-- 5. Serving Reader Role (API Consumers, Analytics, Feature Store Readers)
GRANT USAGE ON SCHEMA customer360, segmentation, core, act, dec, feat, gov, msr TO vteki_serving_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA customer360 TO vteki_serving_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA segmentation TO vteki_serving_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO vteki_serving_reader;
REVOKE ALL ON SCHEMA stg, source FROM vteki_serving_reader;
