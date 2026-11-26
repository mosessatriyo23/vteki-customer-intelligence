"""Prediction lookup must not turn development or malformed rows into serving scores."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base
from api.decision_inputs import load_serving_score_row
from api.models import ModelPredictionRecord, ModelPredictionRun
from services.decision.nba.serving import (
    SCORE_CONTRACT_NOT_SERVING,
    SCORE_STATE_MISSING,
    SCORE_STATE_PRESENT_NOT_APPROVED,
    SCORE_USAGE_NOT_APPROVED,
    lookup_scores,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_prediction(
    db: Session,
    cutoff: str,
    *,
    prediction_type: str = "CHURN",
    contract_status: str = "CONTRACT_COMPLIANT",
    review_status: str = "reviewed",
    customer_id: str = "customer-1",
    score: float = 0.6,
) -> None:
    run = ModelPredictionRun(
        model_version=cutoff,
        feature_set_version="features-v1",
        label_version="labels-v1",
        prediction_type=prediction_type,
        producer_version="producer-v1",
        manifest_hash="hash",
        record_count=1,
        review_status=review_status,
        manifest={},
        submitted_by=1,
        reviewed_by=2,
        imported_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    db.add(run)
    db.flush()
    db.add(
        ModelPredictionRecord(
            run_id=run.id,
            customer_id=customer_id,
            cutoff_at=cutoff,
            score=score,
            band="HIGH",
            contract_status=contract_status,
            reason_codes=[{"code": "RECENCY"}],
            record_fingerprint="fingerprint",
            source_record={},
        )
    )
    db.flush()


def test_only_churn_predictions_are_considered(db: Session):
    add_prediction(db, "2026-11-02T00:00:00+00:00", prediction_type="PROPENSITY")
    add_prediction(db, "2026-11-01T00:00:00+00:00")

    row = load_serving_score_row(db, "customer-1")

    assert row is not None
    assert row["score_generated_at"] == "2026-11-01T00:00:00+00:00"
    assert row["usage_approved"] is None


def test_cutoffs_are_ordered_by_instant_not_text(db: Session):
    add_prediction(db, "2026-11-01T00:00:00+00:00")
    add_prediction(db, "2026-10-31T23:30:00-01:00")

    row = load_serving_score_row(db, "customer-1")

    assert row is not None
    assert row["score_generated_at"] == "2026-10-31T23:30:00-01:00"


@pytest.mark.parametrize("invalid_cutoff", ["not-a-date", "2026-11-03T00:00:00"])
def test_invalid_cutoff_fails_closed_instead_of_using_older_row(
    db: Session, invalid_cutoff: str
):
    add_prediction(db, "2026-11-01T00:00:00+00:00")
    add_prediction(db, invalid_cutoff)

    assert load_serving_score_row(db, "customer-1") is None


@pytest.mark.parametrize("status", ["SCHEMA_PARTIAL", "INVALID_SCORE"])
def test_newer_noncompliant_row_does_not_fall_back_to_older_reviewed_row(
    db: Session, status: str
):
    add_prediction(db, "2026-11-01T00:00:00+00:00", score=0.1)
    add_prediction(db, "2026-11-02T00:00:00+00:00", contract_status=status, score=0.9)

    row = load_serving_score_row(db, "customer-1")

    # The newest row is surfaced (so the UI says "present, not approved"), but it
    # carries its non-serving status; the older clean row is never used instead.
    assert row is not None
    assert row["contract_status"] == status
    assert row["churn_score"] == 0.9
    lookup = lookup_scores(row, customer_id="customer-1")
    assert lookup.unavailable_reason == SCORE_CONTRACT_NOT_SERVING
    assert lookup.state == SCORE_STATE_PRESENT_NOT_APPROVED
    assert lookup.ai_scores is None


def test_noncompliant_churn_does_not_select_other_prediction_type(db: Session):
    add_prediction(db, "2026-11-02T00:00:00+00:00", prediction_type="PROPENSITY")
    add_prediction(db, "2026-11-01T00:00:00+00:00", contract_status="SCHEMA_PARTIAL")

    row = load_serving_score_row(db, "customer-1")

    assert row is not None
    assert row["contract_status"] == "SCHEMA_PARTIAL"
    assert row["score_generated_at"] == "2026-11-01T00:00:00+00:00"


def test_no_churn_row_is_still_missing(db: Session):
    add_prediction(db, "2026-11-02T00:00:00+00:00", prediction_type="PROPENSITY")

    row = load_serving_score_row(db, "customer-1")

    assert row is None
    assert lookup_scores(row, customer_id="customer-1").state == SCORE_STATE_MISSING


def test_pending_review_import_is_present_but_never_usable(db: Session):
    add_prediction(db, "2026-11-01T00:00:00+00:00", review_status="pending_review")

    row = load_serving_score_row(db, "customer-1")
    lookup = lookup_scores(row, customer_id="customer-1")

    assert row["usage_approved"] is None
    assert lookup.state == SCORE_STATE_PRESENT_NOT_APPROVED
    assert lookup.usable is False


def test_reviewed_compliant_row_still_waits_for_usage_approval(db: Session):
    add_prediction(db, "2026-11-01T00:00:00+00:00")

    lookup = lookup_scores(
        load_serving_score_row(db, "customer-1"), customer_id="customer-1"
    )

    assert lookup.unavailable_reason == SCORE_USAGE_NOT_APPROVED
    assert lookup.state == SCORE_STATE_PRESENT_NOT_APPROVED


def test_equal_instant_tie_break_prefers_later_imported_at_over_higher_id(
    db: Session,
):
    # Same instant, written as UTC and as an equivalent +07:00 offset.
    add_prediction(db, "2026-11-01T00:00:00+00:00", score=0.1)
    first_run = db.query(ModelPredictionRun).one()
    add_prediction(db, "2026-11-01T07:00:00+07:00", score=0.9)
    # The first row has the LOWER record id but the LATER import time.
    first_run.imported_at = datetime(2026, 11, 2, tzinfo=timezone.utc)
    db.flush()

    row = load_serving_score_row(db, "customer-1")

    assert row is not None
    assert row["churn_score"] == 0.1


def test_equal_instant_and_imported_at_tie_break_prefers_higher_record_id(
    db: Session,
):
    same_imported_at = datetime(2026, 11, 1, tzinfo=timezone.utc)
    add_prediction(db, "2026-11-01T00:00:00+00:00", score=0.1)
    for run in db.query(ModelPredictionRun).all():
        run.imported_at = same_imported_at
    db.flush()
    add_prediction(db, "2026-11-01T07:00:00+07:00", score=0.9)
    for run in db.query(ModelPredictionRun).all():
        run.imported_at = same_imported_at
    db.flush()

    row = load_serving_score_row(db, "customer-1")

    # Both rows share the same instant and imported_at; the higher record id
    # (the one added last) must win the tie-break deterministically.
    assert row is not None
    assert row["churn_score"] == 0.9
