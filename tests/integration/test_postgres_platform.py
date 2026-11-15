"""PostgreSQL-only governance tests, run after Alembic and db_permissions.sql."""

import argparse
import csv
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from api.models import (
    AuditEvent,
    BatchJob,
    GoldenCustomer,
    IdentityMappingHistory,
    IngestionBatch,
    ProfileSnapshot,
    RegistryVersion,
    ReviewAuditLog,
    ReviewQueueItem,
    User,
)
from generator.generate import run as generate
from services.data.customer360.persistence import save_profile_snapshots
from services.data.customer360.profile import build_profiles_as_of
from services.data.identity.cli import run as resolve
from services.data.ingestion import pg_loader as pg_loader_module
from services.data.ingestion.business_events import get_business_events_as_of
from services.data.ingestion.pg_loader import PostgresIngestionLoader
from services.data.ingestion.transaction_events import (
    append_transaction_event,
    get_transaction_events_as_of,
    project_transaction_as_of,
)
from services.data.ingestion.validator import sha256


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
    catalogue_batch_fk = next(
        foreign_key
        for foreign_key in inspector.get_foreign_keys(
            "transaction_items", schema="source"
        )
        if foreign_key["name"] == "fk_transaction_items_catalogue_batch"
    )
    assert catalogue_batch_fk["constrained_columns"] == [
        "item_code",
        "source_batch_id",
    ]
    assert catalogue_batch_fk["referred_columns"] == [
        "item_code",
        "source_batch_id",
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


def test_postgres_identity_mapping_history_is_append_only(pg_engine: Engine):
    batch_id = f"ci-{uuid4().hex}"
    version_tag = f"ci-{uuid4().hex[:24]}"
    golden_id = str(uuid4())
    now = datetime.now(timezone.utc)

    batch_table = IngestionBatch.__table__
    version_table = RegistryVersion.__table__
    golden_table = GoldenCustomer.__table__
    history_table = IdentityMappingHistory.__table__

    with pg_engine.connect() as connection:
        outer = connection.begin()
        try:
            connection.execute(
                batch_table.insert().values(
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
                version_table.insert().values(
                    version_tag=version_tag,
                    algorithm="ci-test",
                    parameters={},
                    status="ACTIVE",
                    description="Temporary identity history test",
                    created_at=now,
                )
            )

            connection.execute(
                golden_table.insert().values(
                    golden_customer_id=golden_id,
                    first_source_batch_id=batch_id,
                    anchor_source_id=f"source-{uuid4().hex[:12]}",
                    status="PROVISIONAL",
                    merged_into_golden_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )

            source_id = f"source-{uuid4().hex[:12]}"
            history_id = connection.execute(
                history_table.insert()
                .values(
                    source_customer_id=source_id,
                    golden_customer_id=golden_id,
                    registry_version=version_tag,
                    source_batch_id=batch_id,
                    assignment_type="AUTO_MATCH",
                    event_type="BATCH_ASSIGNMENT",
                    effective_at=now,
                    recorded_at=now,
                    reviewer_id=None,
                    correlation_id=f"ci-{uuid4().hex}",
                    change_reason="Temporary append-only integration test",
                )
                .returning(history_table.c.id)
            ).scalar_one()

            assert history_id is not None

            # The database must reject an identical batch assignment event.
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        history_table.insert().values(
                            source_customer_id=source_id,
                            golden_customer_id=golden_id,
                            registry_version=version_tag,
                            source_batch_id=batch_id,
                            assignment_type="AUTO_MATCH",
                            event_type="BATCH_ASSIGNMENT",
                            effective_at=now,
                            recorded_at=now,
                            reviewer_id=None,
                            correlation_id=f"ci-{uuid4().hex}",
                            change_reason="Duplicate event must be rejected",
                        )
                    )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        history_table.update()
                        .where(history_table.c.id == history_id)
                        .values(change_reason="tampered")
                    )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        history_table.delete().where(history_table.c.id == history_id)
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


def test_postgres_customer360_uses_identity_mapping_as_of(pg_engine: Engine):
    batch_id = f"ci-{uuid4().hex}"
    version_tag = f"ci-{uuid4().hex[:24]}"
    now = datetime.now(timezone.utc)

    batch_table = IngestionBatch.__table__
    version_table = RegistryVersion.__table__
    golden_table = GoldenCustomer.__table__
    history_table = IdentityMappingHistory.__table__

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        inbound = root / "inbound"
        resolution = root / "resolution"

        generate(
            argparse.Namespace(
                seed=20260906,
                customers=20,
                as_of_date=date(2026, 9, 6),
                output_dir=inbound,
                ground_truth_dir=root / "truth",
            )
        )
        resolve(
            inbound / "crm_customers.csv",
            resolution,
            synthetic_aliases=True,
        )

        with (resolution / "mapping.csv").open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))

        assert len(rows) >= 2
        mapping = {row["source_customer_id"]: row["golden_customer_id"] for row in rows}

        cutoff = datetime(2026, 9, 7, 0, 0, tzinfo=timezone(timedelta(hours=7)))
        merge_recorded_at = now
        recorded_before = merge_recorded_at - timedelta(seconds=1)
        recorded_after = merge_recorded_at + timedelta(seconds=1)

        # Pilih dua source dengan Golden ID berbeda.
        selected = None
        for source_id, golden_id in mapping.items():
            target = next(
                (
                    (other_source, other_golden)
                    for other_source, other_golden in mapping.items()
                    if other_golden != golden_id
                ),
                None,
            )
            if target:
                selected = (source_id, golden_id, target[1])
                break

        assert selected is not None
        moved_source, old_golden, target_golden = selected

        with pg_engine.connect() as connection:
            outer = connection.begin()
            try:
                connection.execute(
                    batch_table.insert().values(
                        batch_id=batch_id,
                        schema_version="2.0.0",
                        seed=None,
                        as_of_date=date(2026, 9, 6),
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
                    version_table.insert().values(
                        version_tag=version_tag,
                        algorithm="ci-customer360-asof",
                        parameters={},
                        status="ACTIVE",
                        description="Customer360 as-of integration test",
                        created_at=now,
                    )
                )

                golden_ids = set(mapping.values())
                for golden_id in golden_ids:
                    anchor_source = next(
                        source_id
                        for source_id, value in mapping.items()
                        if value == golden_id
                    )
                    connection.execute(
                        golden_table.insert().values(
                            golden_customer_id=golden_id,
                            first_source_batch_id=batch_id,
                            anchor_source_id=anchor_source,
                            status="PROVISIONAL",
                            merged_into_golden_id=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )

                baseline_effective = cutoff - timedelta(days=2)
                baseline_recorded = merge_recorded_at - timedelta(days=2)

                for source_id, golden_id in mapping.items():
                    connection.execute(
                        history_table.insert().values(
                            source_customer_id=source_id,
                            golden_customer_id=golden_id,
                            registry_version=version_tag,
                            source_batch_id=batch_id,
                            assignment_type="BASELINE",
                            event_type="BASELINE",
                            effective_at=baseline_effective,
                            recorded_at=baseline_recorded,
                            reviewer_id=None,
                            correlation_id=f"ci-{uuid4().hex}",
                            change_reason="Initial integration-test mapping",
                        )
                    )

                # Merge berlaku secara efektif sebelum cutoff,
                # tetapi baru diketahui setelah recorded_before.
                connection.execute(
                    history_table.insert().values(
                        source_customer_id=moved_source,
                        golden_customer_id=target_golden,
                        registry_version=version_tag,
                        source_batch_id=batch_id,
                        assignment_type="MANUAL_MERGE",
                        event_type="MANUAL_MERGE",
                        effective_at=cutoff - timedelta(days=1),
                        recorded_at=merge_recorded_at,
                        reviewer_id=None,
                        correlation_id=f"ci-{uuid4().hex}",
                        change_reason="Retroactive merge integration test",
                    )
                )

                with Session(bind=connection) as session:
                    before = build_profiles_as_of(
                        inbound,
                        resolution,
                        cutoff,
                        session,
                        recorded_before,
                    )
                    after = build_profiles_as_of(
                        inbound,
                        resolution,
                        cutoff,
                        session,
                        recorded_after,
                    )

                before_by_id = {row["golden_customer_id"]: row for row in before}
                after_by_id = {row["golden_customer_id"]: row for row in after}

                assert old_golden in before_by_id
                assert target_golden in before_by_id
                assert target_golden in after_by_id

                assert (
                    before_by_id[target_golden]["source_identity_count"] + 1
                    == after_by_id[target_golden]["source_identity_count"]
                )
                assert before_by_id[old_golden][
                    "source_identity_count"
                ] - 1 == after_by_id.get(old_golden, {}).get("source_identity_count", 0)
            finally:
                if outer.is_active:
                    outer.rollback()


def test_postgres_transaction_event_history_loader(pg_engine: Engine):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        inbound = root / "inbound"

        generate(
            argparse.Namespace(
                seed=int(uuid4().hex[:8], 16) % 2_147_483_647,
                customers=20,
                as_of_date=date(2026, 11, 15),
                output_dir=inbound,
                ground_truth_dir=root / "truth",
            )
        )

        with pg_engine.connect() as connection:
            outer = connection.begin()
            try:
                loader = PostgresIngestionLoader(sessionmaker(bind=connection))

                result = loader.ingest(inbound)
                assert result["status"] == "LOADED"
                batch_id = result["batch_id"]

                transaction_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM source.transactions
                        WHERE source_batch_id = :batch_id
                        """
                    ),
                    {"batch_id": batch_id},
                ).scalar_one()

                event_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM source.transaction_event_history
                        WHERE source_batch_id = :batch_id
                        """
                    ),
                    {"batch_id": batch_id},
                ).scalar_one()

                assert transaction_count > 0
                assert event_count == transaction_count
                business_event_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM source.business_event_history
                        WHERE source_batch_id = :batch_id
                        """
                    ),
                    {"batch_id": batch_id},
                ).scalar_one()
                source_business_count = connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM source.customer_visits
                             WHERE source_batch_id = :batch_id)
                          + (SELECT count(*) FROM source.membership_events
                             WHERE source_batch_id = :batch_id)
                        """
                    ),
                    {"batch_id": batch_id},
                ).scalar_one()
                assert business_event_count == source_business_count

                event = (
                    connection.execute(
                        text(
                            """
                        SELECT event_id, occurred_at, available_at, recorded_at
                        FROM source.transaction_event_history
                        WHERE source_batch_id = :batch_id
                        ORDER BY event_id
                        LIMIT 1
                        """
                        ),
                        {"batch_id": batch_id},
                    )
                    .mappings()
                    .one()
                )

                assert event["recorded_at"] >= event["available_at"]
                assert event["occurred_at"] is not None
                business_event = (
                    connection.execute(
                        text(
                            """
                            SELECT event_id, source_customer_ref, source_event_id,
                                   source_version, occurred_at, available_at,
                                   recorded_at
                            FROM source.business_event_history
                            WHERE source_batch_id = :batch_id
                            ORDER BY event_id
                            LIMIT 1
                            """
                        ),
                        {"batch_id": batch_id},
                    )
                    .mappings()
                    .one()
                )
                assert business_event["source_event_id"]
                assert business_event["source_version"]
                assert business_event["recorded_at"] >= business_event["available_at"]

                factory = sessionmaker(bind=connection, expire_on_commit=False)
                with factory() as session:
                    before_available = get_business_events_as_of(
                        session,
                        source_customer_ref=business_event["source_customer_ref"],
                        effective_at=business_event["occurred_at"]
                        + timedelta(seconds=1),
                        known_at=business_event["available_at"]
                        - timedelta(microseconds=1),
                    )
                    after_available = get_business_events_as_of(
                        session,
                        source_customer_ref=business_event["source_customer_ref"],
                        effective_at=business_event["occurred_at"]
                        + timedelta(seconds=1),
                        known_at=business_event["available_at"]
                        + timedelta(microseconds=1),
                    )
                    assert business_event["event_id"] not in {
                        item.event_id for item in before_available
                    }
                    assert business_event["event_id"] in {
                        item.event_id for item in after_available
                    }

                connection.execute(
                    text(
                        "UPDATE stg.ingestion_batches SET status = 'STAGED' "
                        "WHERE batch_id = :batch_id"
                    ),
                    {"batch_id": batch_id},
                )
                with sessionmaker(bind=connection)() as session:
                    unpublished = get_business_events_as_of(
                        session,
                        source_customer_ref=business_event["source_customer_ref"],
                        effective_at=business_event["occurred_at"]
                        + timedelta(seconds=1),
                        known_at=business_event["available_at"] + timedelta(seconds=1),
                    )
                    assert business_event["event_id"] not in {
                        item.event_id for item in unpublished
                    }
                connection.execute(
                    text(
                        "UPDATE stg.ingestion_batches SET status = 'PUBLISHED' "
                        "WHERE batch_id = :batch_id"
                    ),
                    {"batch_id": batch_id},
                )

                replay = loader.ingest(inbound)
                assert replay["status"] == "ALREADY_LOADED"

                replay_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM source.transaction_event_history
                        WHERE source_batch_id = :batch_id
                        """
                    ),
                    {"batch_id": batch_id},
                ).scalar_one()

                assert replay_count == event_count
                replay_business_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM source.business_event_history
                        WHERE source_batch_id = :batch_id
                        """
                    ),
                    {"batch_id": batch_id},
                ).scalar_one()
                assert replay_business_count == business_event_count

                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                UPDATE source.transaction_event_history
                                SET event_type = 'CORRECTION'
                                WHERE event_id = :event_id
                                """
                            ),
                            {"event_id": event["event_id"]},
                        )

                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                DELETE FROM source.transaction_event_history
                                WHERE event_id = :event_id
                                """
                            ),
                            {"event_id": event["event_id"]},
                        )

            finally:
                if outer.is_active:
                    outer.rollback()


def test_postgres_transaction_event_bitemporal_correction(pg_engine: Engine):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        inbound = root / "inbound"
        receipt_batch = root / "receipt_batch"
        correction_batch = root / "correction_batch"

        generate(
            argparse.Namespace(
                seed=int(uuid4().hex[:8], 16) % 2_147_483_647,
                customers=20,
                as_of_date=date(2026, 11, 15),
                output_dir=inbound,
                ground_truth_dir=root / "truth",
            )
        )
        for directory, seed in (
            (receipt_batch, 20261116),
            (correction_batch, 20261117),
        ):
            generate(
                argparse.Namespace(
                    seed=seed,
                    customers=20,
                    as_of_date=date(2026, 11, 15),
                    output_dir=directory,
                    ground_truth_dir=root / f"truth_{seed}",
                )
            )

        with pg_engine.connect() as connection:
            outer = connection.begin()
            try:
                loader = PostgresIngestionLoader(sessionmaker(bind=connection))
                result = loader.ingest(inbound)
                receiving = loader.ingest(receipt_batch)
                correcting = loader.ingest(correction_batch)
                assert result["status"] == "LOADED"
                assert receiving["status"] == "LOADED"
                assert correcting["status"] == "LOADED"
                transaction_batch_id = result["batch_id"]
                receiving_batch_id = receiving["batch_id"]
                correction_batch_id = correcting["batch_id"]

                transaction_id = connection.execute(
                    text(
                        """
                        SELECT source_transaction_id
                        FROM source.transactions
                        WHERE source_batch_id = :batch_id
                          AND status = 'COMPLETED'
                          AND refund_amount = 0
                        LIMIT 1
                        """
                    ),
                    {"batch_id": transaction_batch_id},
                ).scalar_one_or_none()
                assert transaction_id is not None

                factory = sessionmaker(bind=connection, expire_on_commit=False)
                with factory() as session:
                    now = datetime.now(timezone.utc)
                    effective_cutoff = now + timedelta(days=1)
                    publication_known_at = now
                    before_late_event = project_transaction_as_of(
                        session,
                        source_transaction_id=transaction_id,
                        effective_at=effective_cutoff,
                        known_at=publication_known_at,
                    )
                    refund_occurred_at = now - timedelta(minutes=3)

                    with pytest.raises(ValueError, match="source_event_id"):
                        append_transaction_event(
                            session,
                            source_transaction_id=transaction_id,
                            event_type="REFUND_RECORDED",
                            occurred_at=refund_occurred_at,
                            source_batch_id=receiving_batch_id,
                            idempotency_key=f"ci-refund-{uuid4().hex}",
                            payload={"refund_amount": 1},
                            actor_type="SYSTEM",
                        )

                    refund = append_transaction_event(
                        session,
                        source_transaction_id=transaction_id,
                        event_type="REFUND_RECORDED",
                        occurred_at=refund_occurred_at,
                        source_batch_id=receiving_batch_id,
                        idempotency_key=f"ci-refund-{uuid4().hex}",
                        payload={"refund_amount": 1},
                        actor_type="SYSTEM",
                        source_event_id=f"ci-source-{uuid4().hex}",
                        source_version="1",
                    )
                    second_refund = append_transaction_event(
                        session,
                        source_transaction_id=transaction_id,
                        event_type="REFUND_RECORDED",
                        occurred_at=now - timedelta(minutes=2),
                        source_batch_id=receiving_batch_id,
                        idempotency_key=f"ci-refund-{uuid4().hex}",
                        payload={"refund_amount": 2},
                        actor_type="SYSTEM",
                        source_event_id=f"ci-source-{uuid4().hex}",
                        source_version="1",
                    )

                    assert refund.source_batch_id == receiving_batch_id
                    assert refund.source_transaction_batch_id == transaction_batch_id
                    assert second_refund.source_batch_id == receiving_batch_id

                    before_refund = refund.available_at - timedelta(microseconds=1)

                    old_view = get_transaction_events_as_of(
                        session,
                        source_transaction_id=transaction_id,
                        effective_at=effective_cutoff,
                        known_at=before_refund,
                    )
                    assert refund.event_id not in {item.event_id for item in old_view}
                    assert (
                        project_transaction_as_of(
                            session,
                            source_transaction_id=transaction_id,
                            effective_at=effective_cutoff,
                            known_at=publication_known_at,
                        )
                        == before_late_event
                    )

                    replay = append_transaction_event(
                        session,
                        source_transaction_id=transaction_id,
                        event_type="REFUND_RECORDED",
                        occurred_at=refund_occurred_at,
                        source_batch_id=receiving_batch_id,
                        idempotency_key=refund.idempotency_key,
                        payload={"refund_amount": 1},
                        actor_type="SYSTEM",
                        source_event_id=refund.source_event_id,
                        source_version="1",
                    )
                    assert replay.event_id == refund.event_id

                    with pytest.raises(ValueError, match="different event"):
                        append_transaction_event(
                            session,
                            source_transaction_id=transaction_id,
                            event_type="REFUND_RECORDED",
                            occurred_at=refund_occurred_at,
                            source_batch_id=receiving_batch_id,
                            idempotency_key=refund.idempotency_key,
                            payload={"refund_amount": 3},
                            actor_type="SYSTEM",
                            source_event_id=refund.source_event_id,
                            source_version="1",
                        )

                    correction = append_transaction_event(
                        session,
                        source_transaction_id=transaction_id,
                        event_type="CORRECTION",
                        occurred_at=refund_occurred_at,
                        source_batch_id=correction_batch_id,
                        idempotency_key=f"ci-correction-{uuid4().hex}",
                        payload={"refund_amount": 3},
                        actor_type="WORKER",
                        source_event_id=f"ci-correction-source-{uuid4().hex}",
                        source_version="2",
                        corrects_event_id=refund.event_id,
                    )
                    correction_chain = append_transaction_event(
                        session,
                        source_transaction_id=transaction_id,
                        event_type="CORRECTION",
                        occurred_at=refund_occurred_at,
                        source_batch_id=correction_batch_id,
                        idempotency_key=f"ci-correction-{uuid4().hex}",
                        payload={"refund_amount": 4},
                        actor_type="WORKER",
                        source_event_id=f"ci-correction-source-{uuid4().hex}",
                        source_version="3",
                        corrects_event_id=correction.event_id,
                    )
                    status_change = append_transaction_event(
                        session,
                        source_transaction_id=transaction_id,
                        event_type="STATUS_CHANGED",
                        occurred_at=now - timedelta(minutes=1),
                        source_batch_id=correction_batch_id,
                        idempotency_key=f"ci-status-{uuid4().hex}",
                        payload={"status": "CANCELLED"},
                        actor_type="SOURCE",
                        source_event_id=f"ci-status-source-{uuid4().hex}",
                        source_version="1",
                    )

                    between_events = get_transaction_events_as_of(
                        session,
                        source_transaction_id=transaction_id,
                        effective_at=effective_cutoff,
                        known_at=correction.available_at - timedelta(microseconds=1),
                    )
                    between_ids = {item.event_id for item in between_events}
                    assert refund.event_id in between_ids
                    assert correction.event_id not in between_ids
                    assert status_change.event_id not in between_ids

                    after_correction = get_transaction_events_as_of(
                        session,
                        source_transaction_id=transaction_id,
                        effective_at=effective_cutoff,
                        known_at=status_change.available_at + timedelta(microseconds=1),
                    )
                    after_ids = {item.event_id for item in after_correction}
                    assert refund.event_id in after_ids
                    assert correction.event_id in after_ids
                    assert correction_chain.event_id in after_ids
                    assert status_change.event_id in after_ids

                    session.execute(
                        text(
                            "UPDATE stg.ingestion_batches SET status = 'STAGED' "
                            "WHERE batch_id = :batch_id"
                        ),
                        {"batch_id": receiving_batch_id},
                    )
                    while_unpublished = get_transaction_events_as_of(
                        session,
                        source_transaction_id=transaction_id,
                        effective_at=effective_cutoff,
                        known_at=status_change.available_at + timedelta(seconds=1),
                    )
                    unpublished_ids = {item.event_id for item in while_unpublished}
                    assert refund.event_id not in unpublished_ids
                    assert second_refund.event_id not in unpublished_ids
                    session.execute(
                        text(
                            "UPDATE stg.ingestion_batches SET status = 'PUBLISHED' "
                            "WHERE batch_id = :batch_id"
                        ),
                        {"batch_id": receiving_batch_id},
                    )

                    before_status = project_transaction_as_of(
                        session,
                        source_transaction_id=transaction_id,
                        effective_at=status_change.occurred_at
                        - timedelta(microseconds=1),
                        known_at=status_change.available_at + timedelta(microseconds=1),
                    )
                    after_status = project_transaction_as_of(
                        session,
                        source_transaction_id=transaction_id,
                        effective_at=effective_cutoff,
                        known_at=status_change.available_at + timedelta(microseconds=1),
                    )
                    assert before_status.status == "COMPLETED"
                    assert after_status.status == "CANCELLED"
                    assert after_status.cancelled
                    assert after_status.refund_amount == 6
                    assert after_status.actual_revenue == 0
                    assert refund.payload["refund_amount"] == 1
                    assert loader.ingest(receipt_batch)["status"] == "ALREADY_LOADED"

            finally:
                if outer.is_active:
                    outer.rollback()


def test_postgres_multi_batch_ingestion_isolated_and_idempotent(
    pg_engine: Engine,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        inbound_a = root / "batch_a"
        inbound_b = root / "batch_b"

        generate(
            argparse.Namespace(
                seed=20261115,
                customers=20,
                as_of_date=date(2026, 11, 15),
                output_dir=inbound_a,
                ground_truth_dir=root / "truth_a",
            )
        )
        generate(
            argparse.Namespace(
                seed=20261116,
                customers=20,
                as_of_date=date(2026, 11, 15),
                output_dir=inbound_b,
                ground_truth_dir=root / "truth_b",
            )
        )

        with pg_engine.connect() as connection:
            outer = connection.begin()
            try:
                loader = PostgresIngestionLoader(sessionmaker(bind=connection))

                result_a = loader.ingest(inbound_a)
                result_b = loader.ingest(inbound_b)

                assert result_a["status"] == "LOADED"
                assert result_b["status"] == "LOADED"
                assert result_a["batch_id"] != result_b["batch_id"]

                def batch_counts(batch_id: str) -> tuple[int, int]:
                    transactions = connection.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM source.transactions
                            WHERE source_batch_id = :batch_id
                            """
                        ),
                        {"batch_id": batch_id},
                    ).scalar_one()

                    events = connection.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM source.transaction_event_history
                            WHERE source_batch_id = :batch_id
                            """
                        ),
                        {"batch_id": batch_id},
                    ).scalar_one()

                    return transactions, events

                count_a = batch_counts(result_a["batch_id"])
                count_b = batch_counts(result_b["batch_id"])

                assert count_a[0] > 0
                assert count_b[0] > 0
                assert count_a[0] == count_a[1]
                assert count_b[0] == count_b[1]

                ids_a = set(
                    connection.execute(
                        text(
                            """
                            SELECT source_transaction_id
                            FROM source.transactions
                            WHERE source_batch_id = :batch_id
                            """
                        ),
                        {"batch_id": result_a["batch_id"]},
                    ).scalars()
                )
                ids_b = set(
                    connection.execute(
                        text(
                            """
                            SELECT source_transaction_id
                            FROM source.transactions
                            WHERE source_batch_id = :batch_id
                            """
                        ),
                        {"batch_id": result_b["batch_id"]},
                    ).scalars()
                )

                assert ids_a.isdisjoint(ids_b)

                catalogue_matches = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM source.transaction_items AS item
                        JOIN source.catalogue_items AS catalogue
                          ON catalogue.item_code = item.item_code
                         AND catalogue.source_batch_id = item.source_batch_id
                        WHERE item.source_batch_id IN (:batch_a, :batch_b)
                        """
                    ),
                    {
                        "batch_a": result_a["batch_id"],
                        "batch_b": result_b["batch_id"],
                    },
                ).scalar_one()
                transaction_item_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM source.transaction_items
                        WHERE source_batch_id IN (:batch_a, :batch_b)
                        """
                    ),
                    {
                        "batch_a": result_a["batch_id"],
                        "batch_b": result_b["batch_id"],
                    },
                ).scalar_one()
                assert catalogue_matches == transaction_item_count

                replay_a = loader.ingest(inbound_a)
                assert replay_a["status"] == "ALREADY_LOADED"
                assert batch_counts(result_a["batch_id"]) == count_a
                assert batch_counts(result_b["batch_id"]) == count_b

            finally:
                if outer.is_active:
                    outer.rollback()


def _rewrite_csv_field(path: Path, field: str, old_value: str | None, new_value: str):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = list(reader)
    assert fieldnames is not None
    changed = False
    for row in rows:
        if old_value is None or row[field] == old_value:
            row[field] = new_value
            changed = True
            break
    assert changed
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _refresh_manifest_checksums(inbound: Path, file_names: set[str]) -> None:
    manifest_path = inbound / "generation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for file_name in file_names:
        manifest["tables"][file_name]["sha256"] = sha256(inbound / file_name)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_postgres_rejects_source_id_overlap_across_batches_atomically(
    pg_engine: Engine,
):
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        inbound_a = root / "batch_a"
        inbound_b = root / "batch_b"
        for directory, seed in ((inbound_a, 20261120), (inbound_b, 20261121)):
            generate(
                argparse.Namespace(
                    seed=seed,
                    customers=20,
                    as_of_date=date(2026, 11, 15),
                    output_dir=directory,
                    ground_truth_dir=root / f"truth_{seed}",
                )
            )

        with (inbound_a / "transactions.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            overlapping_id = next(csv.DictReader(stream))["source_transaction_id"]
        with (inbound_b / "transactions.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            batch_b_transactions = list(csv.DictReader(stream))
        with (inbound_b / "transaction_items.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            batch_b_item_transaction_ids = {
                row["source_transaction_id"] for row in csv.DictReader(stream)
            }
        replaced_id = next(
            row["source_transaction_id"]
            for row in batch_b_transactions
            if row["source_transaction_id"] in batch_b_item_transaction_ids
        )

        assert overlapping_id != replaced_id
        changed_files = {"transactions.csv", "transaction_items.csv"}
        for file_name in changed_files:
            _rewrite_csv_field(
                inbound_b / file_name,
                "source_transaction_id",
                replaced_id,
                overlapping_id,
            )
        _refresh_manifest_checksums(inbound_b, changed_files)

        loader = PostgresIngestionLoader(sessionmaker(bind=pg_engine))
        loaded_a = loader.ingest(inbound_a)
        assert loaded_a["status"] == "LOADED"
        manifest_b = json.loads(
            (inbound_b / "generation_manifest.json").read_text(encoding="utf-8")
        )
        rejected_batch_id = loader.compute_batch_id(manifest_b)

        with pytest.raises(DBAPIError):
            loader.ingest(inbound_b)

        with pg_engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM source.transactions "
                        "WHERE source_transaction_id = :transaction_id"
                    ),
                    {"transaction_id": overlapping_id},
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM stg.ingestion_batches "
                        "WHERE batch_id = :batch_id"
                    ),
                    {"batch_id": rejected_batch_id},
                ).scalar_one()
                == 0
            )


def test_postgres_rejects_master_data_update_across_batches_atomically(
    pg_engine: Engine,
):
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        inbound_a = root / "batch_a"
        inbound_b = root / "batch_b"
        for directory, seed in ((inbound_a, 20261122), (inbound_b, 20261123)):
            generate(
                argparse.Namespace(
                    seed=seed,
                    customers=20,
                    as_of_date=date(2026, 11, 15),
                    output_dir=directory,
                    ground_truth_dir=root / f"truth_{seed}",
                )
            )
        _rewrite_csv_field(
            inbound_b / "branches.csv",
            "branch_name",
            None,
            "Conflicting branch master-data update",
        )
        _refresh_manifest_checksums(inbound_b, {"branches.csv"})

        loader = PostgresIngestionLoader(sessionmaker(bind=pg_engine))
        assert loader.ingest(inbound_a)["status"] == "LOADED"
        manifest_b = json.loads(
            (inbound_b / "generation_manifest.json").read_text(encoding="utf-8")
        )
        rejected_batch_id = loader.compute_batch_id(manifest_b)

        with pytest.raises(ValueError, match="Conflicting branch definition"):
            loader.ingest(inbound_b)

        with pg_engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM stg.ingestion_batches "
                        "WHERE batch_id = :batch_id"
                    ),
                    {"batch_id": rejected_batch_id},
                ).scalar_one()
                == 0
            )


def test_postgres_concurrent_duplicate_batch_is_idempotent(pg_engine: Engine):
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        inbound = root / "batch"
        generate(
            argparse.Namespace(
                seed=20261118,
                customers=20,
                as_of_date=date(2026, 11, 15),
                output_dir=inbound,
                ground_truth_dir=root / "truth",
            )
        )
        loader = PostgresIngestionLoader(sessionmaker(bind=pg_engine))
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: loader.ingest(inbound), range(2)))

        assert sorted(result["status"] for result in results) == [
            "ALREADY_LOADED",
            "LOADED",
        ]
        batch_id = results[0]["batch_id"]
        with pg_engine.connect() as connection:
            transactions = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM source.transactions
                    WHERE source_batch_id = :batch_id
                    """
                ),
                {"batch_id": batch_id},
            ).scalar_one()
            transaction_events = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM source.transaction_event_history
                    WHERE source_transaction_batch_id = :batch_id
                    """
                ),
                {"batch_id": batch_id},
            ).scalar_one()
            business_events = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM source.business_event_history
                    WHERE source_batch_id = :batch_id
                    """
                ),
                {"batch_id": batch_id},
            ).scalar_one()
            assert transactions == transaction_events
            assert business_events > 0


def test_postgres_batch_job_idempotency_key_is_unique(pg_engine: Engine):
    now = datetime.now(timezone.utc)
    key = f"ci-job-{uuid4().hex}"
    table = BatchJob.__table__
    values = {
        "kind": "ci-idempotency",
        "status": "queued",
        "payload": {"source": "batch"},
        "attempts": 0,
        "max_attempts": 3,
        "available_at": now,
        "claim_token": None,
        "created_by": None,
        "created_at": now,
        "updated_at": now,
        "idempotency_key": key,
    }

    with pg_engine.connect() as connection:
        outer = connection.begin()
        try:
            connection.execute(table.insert().values(**values))
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(table.insert().values(**values))
        finally:
            if outer.is_active:
                outer.rollback()


def test_postgres_ingestion_failure_rolls_back_and_retry_recovers(
    pg_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
):
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        inbound = root / "batch"
        generate(
            argparse.Namespace(
                seed=20261119,
                customers=20,
                as_of_date=date(2026, 11, 15),
                output_dir=inbound,
                ground_truth_dir=root / "truth",
            )
        )
        manifest = json.loads(
            (inbound / "generation_manifest.json").read_text(encoding="utf-8")
        )
        batch_id = PostgresIngestionLoader.compute_batch_id(manifest)
        loader = PostgresIngestionLoader(sessionmaker(bind=pg_engine))
        original_insert = pg_loader_module._insert_typed_rows

        def fail_after_transactions(session, table, rows, table_name):
            original_insert(session, table, rows, table_name)
            if table_name == "transactions":
                raise RuntimeError("Injected failure after transaction rows")

        monkeypatch.setattr(
            pg_loader_module, "_insert_typed_rows", fail_after_transactions
        )
        with pytest.raises(RuntimeError, match="Injected failure"):
            loader.ingest(inbound)

        with pg_engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM stg.ingestion_batches "
                        "WHERE batch_id = :batch_id"
                    ),
                    {"batch_id": batch_id},
                ).scalar_one()
                == 0
            )
            for table_name in (
                "transactions",
                "transaction_event_history",
                "business_event_history",
            ):
                assert (
                    connection.execute(
                        text(
                            f"SELECT count(*) FROM source.{table_name} "
                            "WHERE source_batch_id = :batch_id"
                        ),
                        {"batch_id": batch_id},
                    ).scalar_one()
                    == 0
                )

        monkeypatch.setattr(pg_loader_module, "_insert_typed_rows", original_insert)
        recovered = loader.ingest(inbound)
        assert recovered["status"] == "LOADED"
        assert recovered["batch_id"] == batch_id


def test_postgres_customer360_snapshot_replay_is_immutable(pg_engine: Engine):
    now = datetime.now(timezone.utc)
    batch_a = f"ci-{uuid4().hex}"
    batch_b = f"ci-{uuid4().hex}"
    version_tag = f"ci-{uuid4().hex[:24]}"
    golden_id = str(uuid4())

    with pg_engine.connect() as connection:
        outer = connection.begin()
        try:
            for batch_id in (batch_a, batch_b):
                connection.execute(
                    IngestionBatch.__table__.insert().values(
                        batch_id=batch_id,
                        schema_version="2.0.0",
                        seed=None,
                        as_of_date=date.today(),
                        manifest_payload={},
                        table_checksums={},
                        status="PUBLISHED",
                        rejection_reasons=None,
                        row_counts={},
                        loaded_at=now,
                        published_at=now,
                    )
                )
            connection.execute(
                RegistryVersion.__table__.insert().values(
                    version_tag=version_tag,
                    algorithm="ci-snapshot-immutability",
                    parameters={},
                    status="ACTIVE",
                    description="Customer360 snapshot immutability test",
                    created_at=now,
                )
            )
            connection.execute(
                GoldenCustomer.__table__.insert().values(
                    golden_customer_id=golden_id,
                    first_source_batch_id=batch_a,
                    anchor_source_id=f"source-{uuid4().hex[:12]}",
                    status="PROVISIONAL",
                    merged_into_golden_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )

            factory = sessionmaker(bind=connection, expire_on_commit=False)
            with factory() as session:
                row = {
                    "golden_customer_id": golden_id,
                    "cutoff_at": now.isoformat(),
                    "identity_status": "PROVISIONAL",
                    "source_identity_count": 1,
                    "first_join_date": date.today().isoformat(),
                    "transaction_count": 2,
                    "retained_revenue": 25_000,
                    "last_transaction_at": now.isoformat(),
                    "visit_count": 1,
                    "renewal_count": 0,
                }
                assert (
                    save_profile_snapshots(
                        [row],
                        batch_a,
                        version_tag,
                        session,
                        "ci-rule-v1",
                        commit=False,
                    )
                    == 1
                )
                original = session.query(ProfileSnapshot).one()
                original_generated_at = original.generated_at

                assert (
                    save_profile_snapshots(
                        [row],
                        batch_b,
                        version_tag,
                        session,
                        "ci-rule-v1",
                        commit=False,
                    )
                    == 1
                )
                session.expire_all()
                replay = session.query(ProfileSnapshot).one()
                assert replay.source_batch_id == batch_a
                assert replay.generated_at == original_generated_at

                with pytest.raises(ValueError, match="different payload"):
                    save_profile_snapshots(
                        [{**row, "retained_revenue": 30_000}],
                        batch_b,
                        version_tag,
                        session,
                        "ci-rule-v1",
                        commit=False,
                    )

                session.expire_all()
                persisted = session.query(ProfileSnapshot).one()
                assert persisted.retained_revenue == 25_000
                assert persisted.source_batch_id == batch_a
        finally:
            if outer.is_active:
                outer.rollback()
