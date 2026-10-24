"""PostgreSQL-only governance tests, run after Alembic and db_permissions.sql."""

import os
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from api.models import (
    AuditEvent,
    IngestionBatch,
    RegistryVersion,
    ReviewAuditLog,
    ReviewQueueItem,
    User,
)


@pytest.fixture(scope="module")
def pg_engine() -> Engine:
    url = os.getenv("VTEKI_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("VTEKI_TEST_POSTGRES_URL is not set")
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.skip("PostgreSQL governance tests require PostgreSQL")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        engine.dispose()
        raise
    yield engine
    engine.dispose()


def _insert_audit_event(connection, correlation_id: str) -> int:
    table = AuditEvent.__table__
    return connection.execute(
        table.insert()
        .values(
            request_id=f"ci-{uuid4().hex[:24]}",
            correlation_id=correlation_id,
            actor_id=None,
            event_type="ci.append_only_test",
            entity_type="test",
            entity_id="1",
            details={"test": True},
            method="TEST",
            path="/ci/audit-test",
            status_code=200,
            client_ip=None,
            user_agent=None,
            occurred_at=datetime.now(timezone.utc),
        )
        .returning(table.c.id)
    ).scalar_one()


def test_postgres_schemas_indexes_and_contract_constraints(pg_engine: Engine):
    inspector = inspect(pg_engine)
    schemas = set(inspector.get_schema_names())
    assert {"core", "stg", "feat", "ml", "dec", "act", "msr", "gov"} <= schemas
    assert {"source", "identity", "customer360", "segmentation"} <= schemas

    audit_indexes = {
        item["name"] for item in inspector.get_indexes("audit_event", schema="gov")
    }
    assert "ix_gov_audit_trace_timeline" in audit_indexes

    crm_columns = {
        item["name"]: item
        for item in inspector.get_columns("crm_customers", schema="source")
    }
    assert crm_columns["crm_customer_id"]["type"].length >= 36

    snapshot_uniques = {
        item["name"]: item["column_names"]
        for item in inspector.get_unique_constraints(
            "profile_snapshots", schema="customer360"
        )
    }
    assert snapshot_uniques["uq_c360_profile_snapshot"] == [
        "golden_customer_id",
        "cutoff_at",
        "identity_registry_version",
        "rule_version",
    ]


def test_postgres_audit_event_rejects_update_and_delete(pg_engine: Engine):
    table = AuditEvent.__table__
    with pg_engine.connect() as connection:
        outer = connection.begin()
        try:
            event_id = _insert_audit_event(connection, f"ci-{uuid4().hex}")
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        table.update()
                        .where(table.c.id == event_id)
                        .values(details={"tampered": True})
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(table.delete().where(table.c.id == event_id))
        finally:
            if outer.is_active:
                outer.rollback()


def test_postgres_identity_review_audit_is_append_only(pg_engine: Engine):
    batch_id = f"ci-{uuid4().hex}"
    version_tag = f"ci-{uuid4().hex[:24]}"
    now = datetime.now(timezone.utc)
    audit_table = ReviewAuditLog.__table__

    with pg_engine.connect() as connection:
        outer = connection.begin()
        try:
            connection.execute(
                IngestionBatch.__table__.insert().values(
                    batch_id=batch_id,
                    schema_version="2.0.0",
                    seed=None,
                    as_of_date=date.today(),
                    manifest_payload={},
                    table_checksums={},
                    status="STAGED",
                    rejection_reasons=None,
                    row_counts={},
                    loaded_at=now,
                    published_at=None,
                )
            )
            connection.execute(
                RegistryVersion.__table__.insert().values(
                    version_tag=version_tag,
                    algorithm="ci-test",
                    parameters={},
                    status="ACTIVE",
                    description="Temporary governance test",
                    created_at=now,
                )
            )
            queue_id = connection.execute(
                ReviewQueueItem.__table__.insert()
                .values(
                    source_batch_id=batch_id,
                    registry_version=version_tag,
                    left_source_id=f"left-{uuid4().hex[:12]}",
                    right_source_id=f"right-{uuid4().hex[:12]}",
                    left_golden_id=None,
                    right_golden_id=None,
                    heuristic_score=0.5,
                    reason="ci_test",
                    status="PENDING",
                    reviewer_id=None,
                    reviewer_note=None,
                    decided_at=None,
                    created_at=now,
                )
                .returning(ReviewQueueItem.__table__.c.id)
            ).scalar_one()
            actor_id = connection.execute(
                User.__table__.insert()
                .values(
                    email=f"ci-{uuid4().hex}@example.com",
                    password_hash="not-a-real-password-hash",
                    is_active=True,
                    created_at=now,
                )
                .returning(User.__table__.c.id)
            ).scalar_one()
            audit_id = connection.execute(
                audit_table.insert()
                .values(
                    review_queue_id=queue_id,
                    actor_id=actor_id,
                    action="REJECT_KEEP_SEPARATE",
                    previous_golden_id=None,
                    new_golden_id=None,
                    rationale="temporary CI trigger test",
                    correlation_id=f"ci-{uuid4().hex}",
                    performed_at=now,
                )
                .returning(audit_table.c.id)
            ).scalar_one()

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        audit_table.update()
                        .where(audit_table.c.id == audit_id)
                        .values(rationale="tampered")
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        audit_table.delete().where(audit_table.c.id == audit_id)
                    )
        finally:
            if outer.is_active:
                outer.rollback()


def test_postgres_role_groups_obey_least_privilege(pg_engine: Engine):
    with pg_engine.connect() as connection:
        role_names = set(
            connection.execute(
                text(
                    "SELECT rolname FROM pg_roles WHERE rolname IN "
                    "('vteki_migrator','vteki_ingestion_writer',"
                    "'vteki_identity_reviewer','vteki_serving_reader')"
                )
            ).scalars()
        )
        assert role_names == {
            "vteki_migrator",
            "vteki_ingestion_writer",
            "vteki_identity_reviewer",
            "vteki_serving_reader",
        }
        assert connection.execute(
            text(
                "SELECT bool_and(NOT rolcanlogin) FROM pg_roles WHERE rolname IN "
                "('vteki_migrator','vteki_ingestion_writer',"
                "'vteki_identity_reviewer','vteki_serving_reader')"
            )
        ).scalar_one()

        assert connection.execute(
            text(
                "SELECT has_table_privilege("
                "'vteki_serving_reader', "
                "'customer360.profile_snapshots', 'SELECT')"
            )
        ).scalar_one()
        assert not connection.execute(
            text(
                "SELECT has_schema_privilege("
                "'vteki_serving_reader', 'source', 'USAGE')"
            )
        ).scalar_one()
        assert not connection.execute(
            text(
                "SELECT has_table_privilege("
                "'vteki_ingestion_writer', 'source.crm_customers', 'DELETE')"
            )
        ).scalar_one()
        assert connection.execute(
            text(
                "SELECT has_column_privilege("
                "'vteki_ingestion_writer', 'stg.ingestion_batches', "
                "'status', 'UPDATE')"
            )
        ).scalar_one()
        assert not connection.execute(
            text(
                "SELECT has_column_privilege("
                "'vteki_ingestion_writer', 'stg.ingestion_batches', "
                "'manifest_payload', 'UPDATE')"
            )
        ).scalar_one()
        assert connection.execute(
            text(
                "SELECT has_column_privilege("
                "'vteki_identity_reviewer', 'identity.review_queue', "
                "'status', 'UPDATE')"
            )
        ).scalar_one()
        assert not connection.execute(
            text(
                "SELECT has_column_privilege("
                "'vteki_identity_reviewer', 'identity.golden_customers', "
                "'status', 'UPDATE')"
            )
        ).scalar_one()
