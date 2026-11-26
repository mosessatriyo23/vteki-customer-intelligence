"""Actual Moses producer output survives review import without becoming serving data."""

import hashlib
import json
import os
from uuid import UUID

os.environ["JWT_SECRET"] = "test-only-secret-that-is-long-enough-for-hmac"
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base, get_db
from api.decision_inputs import load_serving_score_row
from api.main import app
from api.models import (
    GoldenCustomer,
    ModelPredictionRecord,
    ModelPredictionRun,
    Role,
    User,
)
from api.security import hash_password
from services.data.models import prediction_contract as pc
from services.data.models.score_explanations import EXPLANATION_VERSION, NOTICE
from services.decision.nba.serving import (
    SCORE_STATE_PRESENT_NOT_APPROVED,
    lookup_scores,
)

CUSTOMER_ID = "6b3ddba4-0825-4e58-a392-d183b71023d0"
CUTOFF = "2026-09-06T00:00:00+07:00"
GENERATED_AT = "2026-09-06T12:00:00+07:00"


def _write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def artifact(tmp_path):
    """Create checksum-linked inputs and return the real on-disk producer output."""
    predictions, reasons, output = (
        tmp_path / name for name in ("predictions", "reasons", "output")
    )
    predictions.mkdir()
    reasons.mkdir()
    prediction = {
        "golden_customer_id": CUSTOMER_ID,
        "cutoff_at": CUTOFF,
        "churn_probability": 0.65,
        "model_version": "model-v1",
        "feature_version": "features-v1",
        "label_version": "labels-v1",
        "horizon_days": 90,
        "generated_at": GENERATED_AT,
        "valid_until": None,
        "contributions": [
            {
                "feature": "recency_days",
                "feature_value": 10,
                "missing": False,
                "imputed_value": 10,
                "log_odds_contribution": 0.2,
            }
        ],
    }
    _write_json(predictions / "predictions.json", [prediction])
    versions = {
        "model_version": "model-v1",
        "feature_version": "features-v1",
        "label_version": "labels-v1",
    }
    _write_json(
        predictions / "prediction_manifest.json",
        {
            **versions,
            "development_only": True,
            "serving_ready": False,
            "generated_at": GENERATED_AT,
            "rows": 1,
            "output_sha256": {
                "predictions.json": _sha(predictions / "predictions.json")
            },
        },
    )
    reason = {
        "golden_customer_id": CUSTOMER_ID,
        "cutoff_at": CUTOFF,
        **versions,
        "status": "OK",
        "reasons": [
            {"code": code, "direction": "INCREASES_RISK", "log_odds_contribution": 0.2}
            for code in ("PURCHASE_RECENCY", "TENURE", "RETAINED_REVENUE_90D")
        ],
    }
    _write_json(reasons / "reasons.json", [reason])
    _write_json(
        reasons / "reasons_manifest.json",
        {
            **versions,
            "development_only": True,
            "serving_ready": False,
            "approved_taxonomy": False,
            "rows": 1,
            "input_sha256": {
                "predictions.json": _sha(predictions / "predictions.json"),
                "prediction_manifest.json": _sha(
                    predictions / "prediction_manifest.json"
                ),
            },
            "output_sha256": {"reasons.json": _sha(reasons / "reasons.json")},
        },
    )
    pc.run(predictions, reasons, output)
    return {
        "manifest": json.loads(
            (output / "contract_manifest.json").read_text(encoding="utf-8")
        ),
        "records": [
            json.loads(line)
            for line in (output / "records.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ],
    }


@pytest.fixture
def review_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        admin, analyst = Role(name="admin"), Role(name="analyst")
        db.add_all([admin, analyst])
        db.flush()
        db.add_all(
            [
                User(
                    email=email,
                    password_hash=hash_password("correct-horse-battery"),
                    roles=[role],
                )
                for email, role in (
                    ("admin@example.com", admin),
                    ("analyst@example.com", analyst),
                )
            ]
        )
        db.add(
            GoldenCustomer(
                golden_customer_id=CUSTOMER_ID,
                first_source_batch_id="batch-1",
                anchor_source_id="source-1",
            )
        )

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.state.audit_session_factory = factory
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        del app.state.audit_session_factory
        engine.dispose()


def _headers(client, email):
    login = client.post(
        "/auth/login", json={"email": email, "password": "correct-horse-battery"}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def assert_present_not_usable(row):
    assert row is not None
    assert row["usage_approved"] is None
    lookup = lookup_scores(row, customer_id=CUSTOMER_ID)
    assert lookup.usable is False
    assert lookup.ai_scores is None
    assert lookup.state == SCORE_STATE_PRESENT_NOT_APPROVED


def _counts(factory):
    with factory() as db:
        return (
            db.scalar(select(func.count()).select_from(ModelPredictionRun)),
            db.scalar(select(func.count()).select_from(ModelPredictionRecord)),
        )


def test_producer_import_preserves_evidence_and_review_cannot_serve(
    artifact, review_client
):
    client, factory = review_client
    submitter = _headers(client, "admin@example.com")
    reviewer = _headers(client, "analyst@example.com")
    source = artifact["records"][0]
    assert UUID(source["customer_id"]) == UUID(CUSTOMER_ID)
    explanation = source["score_explanation"]
    assert explanation["sentences"] == [
        "Dalam perhitungan model, lama sejak aktivitas terakhir mendorong skor churn dalam 90 hari naik."
    ]
    assert explanation["notice"] == NOTICE
    assert explanation["version"] == EXPLANATION_VERSION

    imported = client.post(
        "/model-predictions/runs/import", json=artifact, headers=submitter
    )
    assert imported.status_code == 201, imported.text
    run = imported.json()
    assert {
        key: run[key]
        for key in (
            "model_version",
            "feature_set_version",
            "label_version",
            "producer_version",
        )
    } == {
        key: artifact["manifest"][key]
        for key in (
            "model_version",
            "feature_set_version",
            "label_version",
            "producer_version",
        )
    }
    assert run["review_status"] == "pending_review"
    assert run["serving_ready"] is False
    assert run["manifest"] == artifact["manifest"]
    with factory() as db:
        stored_run = db.scalars(select(ModelPredictionRun)).one()
        for key in (
            "model_version",
            "feature_set_version",
            "label_version",
            "producer_version",
        ):
            assert getattr(stored_run, key) == artifact["manifest"][key]
        assert stored_run.review_status == "pending_review"
        saved = db.scalars(select(ModelPredictionRecord)).one()
        assert saved.source_record == source
        assert (
            saved.record_fingerprint
            == hashlib.sha256(
                json.dumps(source, sort_keys=True, allow_nan=False).encode("utf-8")
            ).hexdigest()
        )
        assert_present_not_usable(load_serving_score_row(db, CUSTOMER_ID))

    before_duplicate = _counts(factory)
    duplicate = client.post(
        "/model-predictions/runs/import", json=artifact, headers=submitter
    )
    assert duplicate.status_code == 409
    assert _counts(factory) == before_duplicate == (1, 1)
    reviewed = client.post(
        f"/model-predictions/runs/{run['id']}/review",
        json={
            "decision": "reviewed",
            "review_note": "Inspected development proposal only",
        },
        headers=reviewer,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review_status"] == "reviewed"
    assert reviewed.json()["serving_ready"] is False
    with factory() as db:
        # A "reviewed" run is still not usage approval: present, never served.
        assert_present_not_usable(load_serving_score_row(db, CUSTOMER_ID))
    assert _counts(factory) == (1, 1)


def test_tampered_explanation_rejected_without_partial_import(artifact, review_client):
    client, factory = review_client
    tampered = json.loads(json.dumps(artifact))
    tampered["records"][0]["score_explanation"]["sentences"][0] = "Invented approval"
    before = _counts(factory)
    response = client.post(
        "/model-predictions/runs/import",
        json=tampered,
        headers=_headers(client, "admin@example.com"),
    )
    assert response.status_code == 400
    assert "checksum" in response.json()["detail"].lower()
    assert _counts(factory) == before == (0, 0)


def test_imported_records_are_readable_for_unlinked_golden_customer(
    artifact, review_client
):
    client, _ = review_client
    headers = _headers(client, "admin@example.com")
    run = client.post("/model-predictions/runs/import", json=artifact, headers=headers)
    assert run.status_code == 201, run.text
    source = artifact["records"][0]
    listed = client.get(
        f"/model-predictions/runs/{run.json()['id']}/records", headers=headers
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    assert body["review_status"] == "pending_review"
    assert body["serving_ready"] is False
    record = body["records"][0]
    assert record["source_record"] == source
    assert record["source_record"]["score_explanation"] == source["score_explanation"]
    assert record["contract_status"] == "SCHEMA_PARTIAL"
    assert record["mapping_candidate"] is None
