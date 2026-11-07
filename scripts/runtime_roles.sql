
-- Runtime database roles for VTEKI.
-- Run as PostgreSQL administrator after Alembic migrations.
-- Passwords must be configured separately; never store them here.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'vteki_api_runtime'
    ) THEN
        CREATE ROLE vteki_api_runtime NOLOGIN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'vteki_worker_runtime'
    ) THEN
        CREATE ROLE vteki_worker_runtime NOLOGIN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'vteki_api'
    ) THEN
        CREATE ROLE vteki_api LOGIN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'vteki_worker'
    ) THEN
        CREATE ROLE vteki_worker LOGIN;
    END IF;
END
$$;

-- Runtime accounts must not own database objects or create schemas.
ALTER ROLE vteki_api NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE vteki_worker NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

GRANT vteki_api_runtime TO vteki_api;
GRANT vteki_worker_runtime TO vteki_worker;

-- API schema access.
GRANT USAGE ON SCHEMA
    core, act, dec, gov, feat, ml, msr, stg,
    identity, customer360, segmentation
TO vteki_api_runtime;

-- Authentication and customer operations.
GRANT SELECT, INSERT, UPDATE ON
    core.users,
    core.user_roles,
    core.customers,
    core.identity_reviews
TO vteki_api_runtime;

GRANT SELECT ON core.roles TO vteki_api_runtime;

-- Campaigns and background job submission.
GRANT SELECT, INSERT, UPDATE ON
    act.campaigns,
    act.batch_jobs
TO vteki_api_runtime;

-- Decisions and human overrides.
GRANT SELECT, INSERT, UPDATE ON
    dec.nba_decisions,
    dec.human_overrides
TO vteki_api_runtime;

-- Audit is append-only: SELECT and INSERT only.
GRANT SELECT, INSERT ON gov.audit_event TO vteki_api_runtime;

GRANT SELECT, INSERT ON gov.decision_traces TO vteki_api_runtime;

-- Customer provenance and monitoring.
GRANT SELECT ON feat.customer_features TO vteki_api_runtime;

GRANT SELECT, INSERT ON ml.model_drift_metrics TO vteki_api_runtime;

GRANT SELECT, INSERT ON msr.campaign_measurements TO vteki_api_runtime;

GRANT SELECT ON stg.pipeline_runs TO vteki_api_runtime;

-- Read-only access for identity and customer 360 views.
GRANT SELECT ON ALL TABLES IN SCHEMA
    identity, customer360, segmentation
TO vteki_api_runtime;

-- Worker schema access.
GRANT USAGE ON SCHEMA core, act, gov, stg TO vteki_worker_runtime;

-- Worker reads customers for simulated campaign execution.
GRANT SELECT ON core.customers TO vteki_worker_runtime;

-- Worker claims, retries, recovers and completes batch jobs.
GRANT SELECT, INSERT, UPDATE ON act.batch_jobs TO vteki_worker_runtime;

-- Worker reads audit summaries and appends audit events.
GRANT SELECT, INSERT ON gov.audit_event TO vteki_worker_runtime;

-- Scheduler creates and updates pipeline run records.
GRANT SELECT, INSERT, UPDATE ON stg.pipeline_runs TO vteki_worker_runtime;

-- Sequence access required for INSERT operations.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA
    core, act, dec, gov, ml, msr
TO vteki_api_runtime;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA
    act, gov, stg
TO vteki_worker_runtime;

-- Explicitly prohibit audit mutation.
REVOKE UPDATE, DELETE, TRUNCATE ON gov.audit_event
    FROM vteki_api_runtime, vteki_worker_runtime;

-- Runtime accounts must not have DDL privileges.
REVOKE CREATE ON SCHEMA
    core, act, dec, gov, feat, ml, msr, stg,
    identity, customer360, segmentation
FROM vteki_api_runtime;

REVOKE CREATE ON SCHEMA core, act, gov, stg
FROM vteki_worker_runtime;
