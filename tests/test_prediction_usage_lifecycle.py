"""HTTP lifecycle of evaluation-only prediction usage authorization.

The complete score below is SYNTHETIC test data, not real model approval or
permission to serve customer actions. Missing production feeds remain missing.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

os.environ["JWT_SECRET"] = "test-only-secret-that-is-long-enough-for-hmac"
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base, get_db
from api.decision_inputs import load_serving_score_row
from api.main import app
from api.models import (
    AuditEvent,
    Customer,
    GoldenCustomer,
    ModelPredictionRecord,
    ModelPredictionRun,
    Role,
    User,
)
from api.security import hash_password
from services.decision.nba.serving import lookup_scores


@pytest.fixture
def lifecycle_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    golden_id = str(uuid4())
    with factory.begin() as db:
        admin, analyst = Role(name="admin"), Role(name="analyst")
        db.add_all([admin, analyst])
        db.flush()
        users = [
            User(
                email=f"{name}@example.com",
                password_hash=hash_password("correct-horse-battery"),
                roles=[role],
            )
            for name, role in (
                ("submitter", admin),
                ("reviewer", analyst),
                ("decider", admin),
            )
        ]
        db.add_all(users)
        db.add(
            GoldenCustomer(
                golden_customer_id=golden_id,
                first_source_batch_id="synthetic-batch",
                anchor_source_id="synthetic-anchor",
                status="APPROVED",
            )
        )
        customer = Customer(
            customer_code="SYNTH-LIFECYCLE",
            full_name="Synthetic Evaluation Customer",
            email="synthetic@example.com",
            segment="test",
            is_demo=False,
            golden_customer_id=golden_id,
        )
        db.add(customer)
        db.flush()
        ids = {
            name: user.id
            for name, user in zip(("submitter", "reviewer", "decider"), users)
        }
        customer_id = customer.id

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.state.audit_session_factory = factory
    try:
        with TestClient(app) as client:
            headers = {}
            for name in ids:
                login = client.post(
                    "/auth/login",
                    json={
                        "email": f"{name}@example.com",
                        "password": "correct-horse-battery",
                    },
                )
                assert login.status_code == 200, login.text
                headers[name] = {
                    "Authorization": f"Bearer {login.json()['access_token']}"
                }
            yield client, factory, golden_id, customer_id, ids, headers
    finally:
        app.dependency_overrides.clear()
        del app.state.audit_session_factory
        engine.dispose()


def synthetic_artifact(golden_id, contract_status="CONTRACT_COMPLIANT"):
    """Evaluation-only synthetic complete score; never a real model approval."""
    versions = {
        "model_version": "synthetic-churn-evaluation-1",
        "feature_set_version": "synthetic-features-1",
        "label_version": "synthetic-labels-1",
    }
    row = {
        **versions,
        "customer_id": golden_id,
        "cutoff_at": datetime.now(timezone.utc).isoformat(),
        "score": 0.92,
        "band": "VERY_HIGH",
        "propensity_purchase": 0.6,
        "propensity_renew": 0.5,
        "clv_amount": 3000000.0,
        "clv_tier": "GOLD",
        "lifecycle_stage": "AT_RISK",
        "reason_codes": ["PURCHASE_FREQUENCY_90D"],
        "contract_status": contract_status,
        "serving_ready": False,
        "approved": False,
    }
    canonical = (json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    manifest = {
        **versions,
        "prediction_type": "CHURN",
        "producer_version": "synthetic-producer-1",
        "development_only": True,
        "serving_ready": False,
        "approved": False,
        "prediction_id_produced": False,
        "rows": 1,
        "output_sha256": {"records.jsonl": hashlib.sha256(canonical).hexdigest()},
    }
    return {"manifest": manifest, "records": [row]}


def evaluate(client, customer_id, headers):
    response = client.post(
        "/decisions/next-best-actions/evaluate",
        json={"customer_id": customer_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def imported_run(client, golden_id, headers, status="CONTRACT_COMPLIANT"):
    artifact = synthetic_artifact(golden_id, status)
    response = client.post(
        "/model-predictions/runs/import", json=artifact, headers=headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["serving_ready"] is False
    return response.json()["id"], artifact


def review_and_approve(client, run_id, ids, headers):
    review = client.post(
        f"/model-predictions/runs/{run_id}/review",
        json={"decision": "reviewed", "review_note": "Synthetic evaluation only"},
        headers=headers["reviewer"],
    )
    assert review.status_code == 200, review.text
    assert review.json()["reviewed_by"] == ids["reviewer"]
    approval = client.post(
        f"/model-predictions/runs/{run_id}/usage",
        json={
            "approved": True,
            "model_author": ids["submitter"],
            "note": "Synthetic evaluation only",
        },
        headers=headers["decider"],
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["serving_ready"] is None
    assert approval.json()["readiness_scope"] == "NOT_EVALUATED_PER_CUSTOMER"


def test_complete_synthetic_score_requires_review_and_usage_then_revocation(
    lifecycle_client,
):
    client, factory, golden_id, customer_id, ids, headers = lifecycle_client
    run_id, artifact = imported_run(client, golden_id, headers["submitter"])
    pending = evaluate(client, customer_id, headers["decider"])
    assert pending["score_state"] == "SCORE_PRESENT_NOT_APPROVED"
    assert pending["score_unavailable_reason"] == "MODEL_RUN_NOT_REVIEWED"
    assert pending["expected_value"] is None

    review = client.post(
        f"/model-predictions/runs/{run_id}/review",
        json={"decision": "reviewed", "review_note": "Synthetic evaluation only"},
        headers=headers["reviewer"],
    )
    assert review.status_code == 200, review.text
    reviewed = evaluate(client, customer_id, headers["decider"])
    assert reviewed["score_state"] == "SCORE_PRESENT_NOT_APPROVED"
    assert reviewed["score_unavailable_reason"] == "MODEL_USAGE_NOT_APPROVED"
    assert reviewed["expected_value"] is None

    approval = client.post(
        f"/model-predictions/runs/{run_id}/usage",
        json={
            "approved": True,
            "model_author": ids["submitter"],
            "note": "Synthetic evaluation only",
        },
        headers=headers["decider"],
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["serving_ready"] is None
    assert approval.json()["readiness_scope"] == "NOT_EVALUATED_PER_CUSTOMER"
    record_view = client.get(
        f"/model-predictions/runs/{run_id}/records", headers=headers["decider"]
    ).json()
    assert record_view["serving_ready"] is None
    assert record_view["readiness_scope"] == "NOT_EVALUATED_PER_CUSTOMER"
    with factory() as db:
        loaded = load_serving_score_row(db, golden_id)
        assert loaded["usage_approved"] is True
        assert loaded["model_version"] == artifact["manifest"]["model_version"]
        assert lookup_scores(loaded, customer_id=golden_id).usable is True
    ready = evaluate(client, customer_id, headers["decider"])
    assert ready["score_state"] == "SCORE_READY"
    assert ready["score_unavailable_reason"] is None
    assert (
        ready["serving_ready"] is False
    )  # consent, complaints and eligibility are not wired
    assert ready["expected_value"] is None
    assert {
        "consent",
        "complaint_history",
        "eligibility",
        "product_suitability",
    } <= set(ready["unavailable_sources"])

    revoked = client.post(
        f"/model-predictions/runs/{run_id}/usage",
        json={"approved": False, "note": "Withdraw synthetic evaluation authorization"},
        headers=headers["decider"],
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["usage_approved"] is False
    revoked_view = client.get(
        f"/model-predictions/runs/{run_id}/records", headers=headers["decider"]
    ).json()
    assert revoked_view["serving_ready"] is False
    after = evaluate(client, customer_id, headers["decider"])
    assert after["score_state"] == "SCORE_PRESENT_NOT_APPROVED"
    assert after["score_unavailable_reason"] == "MODEL_USAGE_NOT_APPROVED"
    assert after["expected_value"] is None
    with factory() as db:
        run = db.get(ModelPredictionRun, run_id)
        record = db.scalars(
            select(ModelPredictionRecord).where(ModelPredictionRecord.run_id == run_id)
        ).one()
        assert run.reviewed_by == ids["reviewer"]
        assert run.model_author == ids["submitter"]
        assert record.contract_status == "CONTRACT_COMPLIANT"
        assert record.source_record == artifact["records"][0]
        assert record.source_record["serving_ready"] is False
        assert record.source_record["approved"] is False
        assert all(
            record.source_record[key] == artifact["manifest"][key]
            for key in ("model_version", "feature_set_version", "label_version")
        )
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "model_prediction_run",
                AuditEvent.entity_id == str(run_id),
            )
        ).all()
        assert {
            "model.prediction_run.imported_for_review",
            "model.prediction_run.reviewed",
            "model.prediction_run.usage_approved",
            "model.prediction_run.usage_revoked",
        } <= {event.event_type for event in events}
        assert all(
            event.actor_id == ids["decider"]
            for event in events
            if event.event_type
            in (
                "model.prediction_run.usage_approved",
                "model.prediction_run.usage_revoked",
            )
        )


def test_partial_contract_stays_unusable_even_after_independent_approval(
    lifecycle_client,
):
    client, factory, golden_id, customer_id, ids, headers = lifecycle_client
    run_id, _ = imported_run(client, golden_id, headers["submitter"], "SCHEMA_PARTIAL")
    review_and_approve(client, run_id, ids, headers)
    with factory() as db:
        loaded = load_serving_score_row(db, golden_id)
        assert loaded["contract_status"] == "SCHEMA_PARTIAL"
        result = lookup_scores(loaded, customer_id=golden_id)
        assert result.usable is False
        assert result.unavailable_reason == "SCORE_CONTRACT_NOT_SERVING"
    response = evaluate(client, customer_id, headers["decider"])
    assert response["score_state"] == "SCORE_PRESENT_NOT_APPROVED"
    assert response["score_unavailable_reason"] == "SCORE_CONTRACT_NOT_SERVING"
    assert response["expected_value"] is None
    assert response["serving_ready"] is False
