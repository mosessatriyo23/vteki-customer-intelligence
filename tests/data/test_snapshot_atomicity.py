"""Regression tests for whole-batch validation and immutable snapshot replay."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base
from api.models import (
    GoldenCustomer,
    ProfileSnapshot,
    RegistryVersion,
    RFMLifecycleSnapshot,
)
from services.data.customer360.persistence import save_profile_snapshots
from services.data.segmentation.persistence import save_segmentation_snapshots


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    session.add(
        RegistryVersion(version_tag="identity-v1", algorithm="test", parameters={})
    )
    session.add(
        GoldenCustomer(
            golden_customer_id="golden-1",
            first_source_batch_id="seed-batch",
            anchor_source_id="source-1",
            status="PROVISIONAL",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
    return engine, session


def c360_row(**overrides):
    result = {
        "golden_customer_id": "golden-1",
        "cutoff_at": "2026-09-06T00:00:00+07:00",
        "identity_status": "PROVISIONAL",
        "source_identity_count": 1,
        "first_join_date": "2026-01-01",
        "transaction_count": 4,
        "retained_revenue": 100_000,
        "last_transaction_at": "2026-09-01T12:00:00+07:00",
        "visit_count": 3,
        "renewal_count": 0,
    }
    result.update(overrides)
    return result


def rfm_row(**overrides):
    result = {
        "golden_customer_id": "golden-1",
        "cutoff_at": "2026-09-06T00:00:00+07:00",
        "identity_status": "PROVISIONAL",
        "recency_days": 5,
        "frequency": 4,
        "monetary": 100_000,
        "rfm_window_days": 365,
        "r_score": 5,
        "f_score": 3,
        "m_score": 3,
        "rfm_code": "533",
        "tenure_days": 248,
        "transactions_60d": 3,
        "transactions_90d": 4,
        "revenue_90d": 100_000,
        "lifecycle": "LOYAL",
        "rule_version": "lifecycle-proposed-1.0",
    }
    result.update(overrides)
    return result


def test_customer360_validates_entire_batch_before_mutating_existing_snapshot():
    engine, session = make_session()
    try:
        save_profile_snapshots(
            [c360_row()], "batch-1", "identity-v1", session, "rule-1"
        )
        first = session.scalars(select(ProfileSnapshot)).one()
        first_generated_at = first.generated_at

        # Row one would previously have updated an ORM object before row two failed.
        with pytest.raises(ValueError, match="retained_revenue"):
            save_profile_snapshots(
                [
                    c360_row(retained_revenue=999_000),
                    c360_row(
                        retained_revenue=12.5,
                        cutoff_at="2026-09-07T00:00:00+07:00",
                    ),
                ],
                "batch-2",
                "identity-v1",
                session,
                "rule-1",
            )
        session.expire_all()
        current = session.scalars(select(ProfileSnapshot)).one()
        assert current.retained_revenue == 100_000
        assert current.source_batch_id == "batch-1"
        assert _as_utc(current.generated_at) == _as_utc(first_generated_at)
    finally:
        session.close()
        engine.dispose()


def test_customer360_replay_is_noop_and_versioned_payload_cannot_be_overwritten():
    engine, session = make_session()
    try:
        save_profile_snapshots(
            [c360_row()], "batch-1", "identity-v1", session, "rule-1"
        )
        first = session.scalars(select(ProfileSnapshot)).one()
        first_generated_at = first.generated_at
        assert (
            save_profile_snapshots(
                [c360_row()], "batch-2", "identity-v1", session, "rule-1"
            )
            == 1
        )
        session.expire_all()
        replay = session.scalars(select(ProfileSnapshot)).one()
        assert replay.source_batch_id == "batch-1"
        assert _as_utc(replay.generated_at) == _as_utc(first_generated_at)
        with pytest.raises(ValueError, match="different payload"):
            save_profile_snapshots(
                [c360_row(retained_revenue=200_000)],
                "batch-3",
                "identity-v1",
                session,
                "rule-1",
            )
        session.expire_all()
        snapshot = session.scalars(select(ProfileSnapshot)).one()
        assert snapshot.retained_revenue == 100_000
    finally:
        session.close()
        engine.dispose()


def test_segmentation_validates_entire_batch_before_mutating_existing_snapshot():
    engine, session = make_session()
    try:
        save_segmentation_snapshots([rfm_row()], "batch-1", "identity-v1", session)
        first = session.scalars(select(RFMLifecycleSnapshot)).one()
        first_generated_at = first.generated_at

        with pytest.raises(ValueError, match="monetary"):
            save_segmentation_snapshots(
                [
                    rfm_row(monetary=999_000),
                    rfm_row(
                        monetary=1.25,
                        cutoff_at="2026-09-07T00:00:00+07:00",
                    ),
                ],
                "batch-2",
                "identity-v1",
                session,
            )
        session.expire_all()
        current = session.scalars(select(RFMLifecycleSnapshot)).one()
        assert current.monetary == 100_000
        assert current.source_batch_id == "batch-1"
        assert _as_utc(current.generated_at) == _as_utc(first_generated_at)
    finally:
        session.close()
        engine.dispose()


def test_segmentation_replay_is_noop_and_versioned_payload_cannot_be_overwritten():
    engine, session = make_session()
    try:
        save_segmentation_snapshots([rfm_row()], "batch-1", "identity-v1", session)
        first = session.scalars(select(RFMLifecycleSnapshot)).one()
        first_generated_at = first.generated_at
        assert (
            save_segmentation_snapshots([rfm_row()], "batch-2", "identity-v1", session)
            == 1
        )
        session.expire_all()
        replay = session.scalars(select(RFMLifecycleSnapshot)).one()
        assert replay.source_batch_id == "batch-1"
        assert _as_utc(replay.generated_at) == _as_utc(first_generated_at)
        with pytest.raises(ValueError, match="different payload"):
            save_segmentation_snapshots(
                [rfm_row(monetary=200_000)], "batch-3", "identity-v1", session
            )
        session.expire_all()
        assert session.scalars(select(RFMLifecycleSnapshot)).one().monetary == 100_000
    finally:
        session.close()
        engine.dispose()
