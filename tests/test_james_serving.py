"""Serving boundary tests; use SQLite as a deterministic contract test database."""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base
from api.models import (
    GoldenCustomer,
    IngestionBatch,
    ProfileSnapshot,
    RegistryVersion,
    RFMLifecycleSnapshot,
)
from services.data.customer360.publish import publish_serving_snapshots

CUTOFF = "2026-09-06T23:59:59+07:00"


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all(
            [
                IngestionBatch(
                    batch_id="batch-1",
                    schema_version="2.0.0",
                    as_of_date=date(2026, 9, 6),
                    status="PUBLISHED",
                ),
                RegistryVersion(version_tag="v1", algorithm="test"),
                GoldenCustomer(
                    golden_customer_id="gold-1",
                    first_source_batch_id="batch-1",
                    anchor_source_id="source-1",
                    status="PROVISIONAL",
                ),
            ]
        )
    yield factory
    engine.dispose()


def profile():
    return {
        "golden_customer_id": "gold-1",
        "cutoff_at": CUTOFF,
        "identity_status": "PROVISIONAL",
        "source_identity_count": 1,
        "first_join_date": "2026-01-01",
        "transaction_count": 5,
        "retained_revenue": 1500000,
        "last_transaction_at": None,
        "visit_count": 2,
        "renewal_count": 0,
    }


def segment():
    return {
        "golden_customer_id": "gold-1",
        "cutoff_at": CUTOFF,
        "identity_status": "PROVISIONAL",
        "recency_days": 5,
        "frequency": 5,
        "monetary": 1500000,
        "r_score": 5,
        "f_score": 3,
        "m_score": 3,
        "rfm_code": "533",
        "tenure_days": 248,
        "transactions_60d": 3,
        "transactions_90d": 5,
        "revenue_90d": 1500000,
        "lifecycle": "LOYAL",
    }


def publish(factory, profiles=None, segments=None, batch="batch-1"):
    return publish_serving_snapshots(
        factory,
        profiles=[profile()] if profiles is None else profiles,
        segments=[segment()] if segments is None else segments,
        batch_id=batch,
        registry_version="v1",
    )


def counts(factory):
    with factory() as db:
        return (
            db.scalar(select(func.count()).select_from(ProfileSnapshot)),
            db.scalar(select(func.count()).select_from(RFMLifecycleSnapshot)),
        )


def test_atomic_publish_and_replay(session_factory):
    assert publish(session_factory)["status"] == "PUBLISHED"
    assert counts(session_factory) == (1, 1)
    assert publish(session_factory)["status"] == "PUBLISHED"
    assert counts(session_factory) == (1, 1)


def test_rfm_failure_rolls_back_profile(session_factory):
    broken = dict(segment(), monetary=1.1)
    with pytest.raises(ValueError, match="integer IDR"):
        publish(session_factory, segments=[broken])
    assert counts(session_factory) == (0, 0)


def test_source_batch_must_be_published(session_factory):
    with pytest.raises(ValueError, match="Source batch must be PUBLISHED"):
        publish(session_factory, batch="other-batch")
    assert counts(session_factory) == (0, 0)


def test_snapshot_sets_must_match(session_factory):
    with pytest.raises(ValueError, match="must match"):
        publish(session_factory, segments=[dict(segment(), golden_customer_id="other")])
    assert counts(session_factory) == (0, 0)


def test_conflicting_replay_is_rejected(session_factory):
    publish(session_factory)
    with pytest.raises(ValueError, match="Conflicting Customer 360"):
        publish(session_factory, profiles=[dict(profile(), retained_revenue=1200000)])
    assert counts(session_factory) == (1, 1)


def test_negative_money_and_naive_datetime_rejected(session_factory):
    with pytest.raises(ValueError, match="nonnegative"):
        publish(session_factory, profiles=[dict(profile(), retained_revenue=-10)])
    with pytest.raises(ValueError, match="timezone-aware"):
        publish(
            session_factory, profiles=[dict(profile(), cutoff_at=datetime(2026, 9, 6))]
        )
    assert counts(session_factory) == (0, 0)
