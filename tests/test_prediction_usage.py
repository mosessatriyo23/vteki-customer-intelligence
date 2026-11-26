"""Run-level usage authorization is a separate, audited admin decision."""

import os
from datetime import datetime, timezone

os.environ["JWT_SECRET"] = "test-only-secret-that-is-long-enough-for-hmac"
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base, get_db
from api.main import app
from api.models import AuditEvent, ModelPredictionRun, Role, User
from api.security import hash_password


@pytest.fixture
def usage_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        admin = Role(name="admin")
        analyst = Role(name="analyst")
        db.add_all([admin, analyst])
        db.flush()
        users = [
            User(
                email=email,
                password_hash=hash_password("correct-horse-battery"),
                roles=[role],
            )
            for email, role in (
                ("submitter@example.com", admin),
                ("reviewer@example.com", analyst),
                ("decider@example.com", admin),
            )
        ]
        db.add_all(users)
        db.flush()
        ids = {user.email.split("@")[0]: user.id for user in users}
        run = ModelPredictionRun(
            model_version="v1",
            feature_set_version="f1",
            label_version="l1",
            prediction_type="CHURN",
            producer_version="p1",
            manifest_hash="hash",
            record_count=1,
            review_status="pending_review",
            manifest={"model_author": ids["reviewer"]},
            submitted_by=ids["submitter"],
        )
        db.add(run)
        db.flush()
        run_id = run.id

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
                assert login.status_code == 200
                headers[name] = {
                    "Authorization": f"Bearer {login.json()['access_token']}"
                }
            yield client, factory, run_id, ids, headers
    finally:
        app.dependency_overrides.clear()
        del app.state.audit_session_factory
        engine.dispose()


def _usage(client, run_id, headers, approved, author=None, note="Approved for use"):
    return client.post(
        f"/model-predictions/runs/{run_id}/usage",
        json={"approved": approved, "model_author": author, "note": note},
        headers=headers,
    )


def test_approval_requires_independent_completed_review_and_persists_audit(
    usage_client,
):
    client, factory, run_id, ids, headers = usage_client
    initial = client.get("/model-predictions/runs", headers=headers["decider"]).json()[
        0
    ]
    assert initial["usage_approved"] is None
    assert initial["model_author"] is None  # manifest cannot declare trusted author
    assert initial["usage_decided_by"] is None
    assert initial["usage_decided_at"] is None
    assert initial["usage_note"] is None
    assert (
        _usage(client, run_id, headers["decider"], True, ids["submitter"]).status_code
        == 409
    )
    with factory.begin() as db:
        run = db.get(ModelPredictionRun, run_id)
        run.review_status = "reviewed"
        run.reviewed_by = ids["reviewer"]
    assert (
        _usage(client, run_id, headers["decider"], True, ids["submitter"]).status_code
        == 409
    )
    with factory.begin() as db:
        db.get(ModelPredictionRun, run_id).reviewed_at = datetime.now(timezone.utc)
    approved = _usage(client, run_id, headers["decider"], True, ids["submitter"])
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["usage_approved"] is True
    assert body["model_author"] == ids["submitter"]
    assert body["usage_decided_by"] == ids["decider"]
    assert datetime.fromisoformat(body["usage_decided_at"]).tzinfo is not None
    assert body["usage_note"] == "Approved for use"
    assert body["serving_ready"] is None
    assert body["readiness_scope"] == "NOT_EVALUATED_PER_CUSTOMER"
    listed = client.get("/model-predictions/runs", headers=headers["reviewer"]).json()
    assert listed[0]["usage_approved"] is True
    with factory() as db:
        run = db.get(ModelPredictionRun, run_id)
        assert run.usage_approved is True
        assert run.model_author == ids["submitter"]
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "model_prediction_run",
                AuditEvent.entity_id == str(run_id),
            )
        ).all()
        assert any(
            event.event_type == "model.prediction_run.usage_approved"
            and event.actor_id == ids["decider"]
            and event.details["model_author"] == ids["submitter"]
            for event in events
        )
    revoked = _usage(client, run_id, headers["decider"], False, None, "Withdrawn")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["usage_approved"] is False
    assert revoked.json()["model_author"] == ids["submitter"]
    with factory() as db:
        assert db.get(ModelPredictionRun, run_id).usage_approved is False
        assert any(
            event.event_type == "model.prediction_run.usage_revoked"
            for event in db.scalars(select(AuditEvent)).all()
        )


def test_approval_refuses_self_review_author_review_rejection_and_unknown_author(
    usage_client,
):
    client, factory, run_id, ids, headers = usage_client
    with factory.begin() as db:
        run = db.get(ModelPredictionRun, run_id)
        run.review_status = "reviewed"
        run.reviewed_at = datetime.now(timezone.utc)
        run.reviewed_by = ids["submitter"]
    assert (
        _usage(client, run_id, headers["decider"], True, ids["decider"]).status_code
        == 409
    )
    with factory.begin() as db:
        db.get(ModelPredictionRun, run_id).reviewed_by = ids["reviewer"]
    assert (
        _usage(client, run_id, headers["decider"], True, ids["reviewer"]).status_code
        == 409
    )
    assert _usage(client, run_id, headers["decider"], True, 999999).status_code == 404
    with factory.begin() as db:
        db.get(ModelPredictionRun, run_id).review_status = "rejected"
    assert (
        _usage(client, run_id, headers["decider"], True, ids["submitter"]).status_code
        == 409
    )
    with factory() as db:
        assert db.get(ModelPredictionRun, run_id).usage_approved is None


def test_usage_requires_auth_admin_and_valid_request(usage_client):
    client, _, run_id, ids, headers = usage_client
    url = f"/model-predictions/runs/{run_id}/usage"
    payload = {"approved": True, "model_author": ids["submitter"], "note": "reason"}
    assert client.post(url, json=payload).status_code == 401
    assert (
        client.post(url, json=payload, headers=headers["reviewer"]).status_code == 403
    )
    assert (
        client.post(
            "/model-predictions/runs/999999/usage",
            json=payload,
            headers=headers["decider"],
        ).status_code
        == 404
    )
    for invalid in (
        {**payload, "approved": "true"},
        {**payload, "approved": 1},
        {**payload, "model_author": None},
        {**payload, "model_author": 0},
        {**payload, "model_author": "1"},
        {"approved": False, "model_author": ids["reviewer"], "note": "reason"},
        {**payload, "note": "  "},
        {**payload, "note": "x" * 2001},
    ):
        assert (
            client.post(url, json=invalid, headers=headers["decider"]).status_code
            == 422
        )


def test_usage_schema_documents_conditional_author_and_note(usage_client):
    client, _, _, _, _ = usage_client
    operation = client.get("/openapi.json").json()["paths"][
        "/model-predictions/runs/{run_id}/usage"
    ]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert len(schema["oneOf"]) == 2
    definitions = client.get("/openapi.json").json()["components"]["schemas"]
    approval = definitions["PredictionUsageApproval"]
    assert "model_author" in approval["required"]
    assert approval["properties"]["approved"]["const"] is True
    assert approval["properties"]["model_author"]["exclusiveMinimum"] == 0
    assert approval["properties"]["note"]["maxLength"] == 2000
    assert "pattern" in approval["properties"]["note"]
    assert "422" in operation["responses"]


def test_audit_failure_rolls_back_usage_decision(usage_client):
    from sqlalchemy import event

    client, factory, run_id, ids, headers = usage_client

    def reject_business_audit(mapper, connection, target):
        if target.event_type == "model.prediction_run.usage_revoked":
            raise RuntimeError("audit write unavailable")

    event.listen(AuditEvent, "before_insert", reject_business_audit)
    try:
        with pytest.raises(RuntimeError, match="audit write unavailable"):
            _usage(client, run_id, headers["decider"], False, None, "Revoke")
    finally:
        event.remove(AuditEvent, "before_insert", reject_business_audit)
    with factory() as db:
        run = db.get(ModelPredictionRun, run_id)
        assert run.usage_approved is None
        assert run.usage_decided_by is None
        assert run.usage_decided_at is None
        assert run.usage_note is None
        assert (
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.event_type == "model.prediction_run.usage_revoked"
                )
            ).first()
            is None
        )


def test_revocation_allowed_before_review_and_preserves_author(usage_client):
    client, factory, run_id, ids, headers = usage_client
    with factory.begin() as db:
        db.get(ModelPredictionRun, run_id).model_author = ids["submitter"]
    revoked = _usage(client, run_id, headers["decider"], False, None, "Not authorized")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["usage_approved"] is False
    assert revoked.json()["model_author"] == ids["submitter"]
    assert revoked.json()["usage_note"] == "Not authorized"
    with factory() as db:
        run = db.get(ModelPredictionRun, run_id)
        assert run.usage_approved is False
        assert run.model_author == ids["submitter"]
        assert any(
            event.event_type == "model.prediction_run.usage_revoked"
            and event.actor_id == ids["decider"]
            for event in db.scalars(select(AuditEvent)).all()
        )
