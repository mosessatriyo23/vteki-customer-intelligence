-- VTEKI role groups: run as DB administrator AFTER Alembic migrations.
-- Credentials are NOT stored in source control. Provision LOGIN principals
-- independently, then GRANT a NOLOGIN group to each principal.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vteki_migrator') THEN
        CREATE ROLE vteki_migrator NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vteki_ingestion_writer') THEN
        CREATE ROLE vteki_ingestion_writer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vteki_identity_reviewer') THEN
        CREATE ROLE vteki_identity_reviewer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vteki_serving_reader') THEN
        CREATE ROLE vteki_serving_reader NOLOGIN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname IN
        ('vteki_migrator','vteki_ingestion_writer','vteki_identity_reviewer','vteki_serving_reader')
        AND rolcanlogin
    ) THEN
        RAISE EXCEPTION 'One or more legacy group roles have LOGIN. Rotate and migrate existing principals first.';
    END IF;
END $$;

-- Migrations require a real DDL owner; CREATE on a schema alone does not
-- allow ALTER of tables owned by other roles.
GRANT USAGE, CREATE ON SCHEMA core, stg, feat, ml, dec, act, msr, gov,
    source, identity, customer360, segmentation TO vteki_migrator;

-- First revoke the broad grants that the legacy script may have assigned.
REVOKE ALL ON SCHEMA identity, customer360, segmentation
    FROM vteki_ingestion_writer;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA identity, customer360, segmentation
    FROM vteki_ingestion_writer;
REVOKE DELETE, UPDATE ON ALL TABLES IN SCHEMA stg, source
    FROM vteki_ingestion_writer;
GRANT USAGE ON SCHEMA stg, source TO vteki_ingestion_writer;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA stg, source TO vteki_ingestion_writer;
-- stg allows controlled batch publication updates; no DELETE of published source.
GRANT UPDATE (status, published_at) ON stg.ingestion_batches TO vteki_ingestion_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA stg, source TO vteki_ingestion_writer;

REVOKE ALL ON SCHEMA core, gov FROM vteki_identity_reviewer;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA gov FROM vteki_identity_reviewer;
GRANT USAGE ON SCHEMA identity TO vteki_identity_reviewer;
GRANT SELECT ON identity.golden_customers, identity.source_identity_mapping,
    identity.match_decisions, identity.review_queue, identity.registry_versions
    TO vteki_identity_reviewer;
GRANT UPDATE (status, reviewer_id, reviewer_note, decided_at)
    ON identity.review_queue TO vteki_identity_reviewer;
GRANT INSERT, SELECT ON identity.review_audit_log TO vteki_identity_reviewer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA identity TO vteki_identity_reviewer;

REVOKE ALL ON SCHEMA core, gov, act, dec, feat, stg, source
    FROM vteki_serving_reader;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA core, gov, act, dec, feat, stg, source
    FROM vteki_serving_reader;
GRANT USAGE ON SCHEMA customer360, segmentation, msr TO vteki_serving_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA customer360, segmentation, msr TO vteki_serving_reader;
-- Never grant core.users (password_hash), raw/source data or audit internals
-- to the public/read-only analytics group.
REVOKE ALL ON SCHEMA stg, source FROM vteki_serving_reader;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='evaluation') THEN
        REVOKE ALL ON SCHEMA evaluation FROM vteki_ingestion_writer,
            vteki_identity_reviewer, vteki_serving_reader;
    END IF;
END $$;
-- Set ALTER DEFAULT PRIVILEGES separately AS the actual migration/DDL owner.
-- Sample provisioning outside Git: GRANT vteki_ingestion_writer TO my_loader_login;
