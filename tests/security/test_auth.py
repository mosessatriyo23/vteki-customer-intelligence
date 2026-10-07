import os

os.environ["JWT_SECRET"] = "test-only-secret-that-is-long-enough-for-hmac"
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import Base, get_db
from api.main import app
from api.models import (
    AuditEvent,
    BatchJob,
    Campaign,
    Customer,
    DecisionTrace,
    HumanOverride,
    Role,
    User,
)
from api.security import hash_password, verify_password
from worker import tasks as worker_tasks
from worker.runner import process_one


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(
        schema_translate_map={
            "core": None,
            "gov": None,
            "stg": None,
            "feat": None,
            "ml": None,
            "dec": None,
            "act": None,
            "msr": None,
        }
    )
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with TestingSession() as db:
        admin = Role(name="admin")
        analyst = Role(name="analyst")
        campaign_manager = Role(name="campaign_manager")
        db.add_all([admin, analyst, campaign_manager])
        db.flush()
        db.add_all(
            [
                User(
                    email="admin@example.com",
                    password_hash=hash_password("correct-horse-battery"),
                    roles=[admin],
                ),
                User(
                    email="analyst@example.com",
                    password_hash=hash_password("correct-horse-battery"),
                    roles=[analyst],
                ),
                User(
                    email="campaign@example.com",
                    password_hash=hash_password("correct-horse-battery"),
                    roles=[campaign_manager],
                ),
            ]
        )
        db.commit()

    def override_get_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.state.audit_session_factory = TestingSession
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.audit_session_factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def token_for(client: TestClient, email: str) -> str:
    response = client.post(
        "/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_login_and_current_user(client: TestClient):
    token = token_for(client, "analyst@example.com")
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["roles"] == ["analyst"]


def test_rbac_rejects_analyst_and_allows_admin(client: TestClient):
    analyst_token = token_for(client, "analyst@example.com")
    admin_token = token_for(client, "admin@example.com")
    assert (
        client.get(
            "/admin/health", headers={"Authorization": f"Bearer {analyst_token}"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/admin/health", headers={"Authorization": f"Bearer {admin_token}"}
        ).status_code
        == 200
    )


def test_login_rejects_invalid_password(client: TestClient):
    response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "not-the-password"},
    )
    assert response.status_code == 401


def test_bcrypt_hash_verifies_long_password_without_truncation():
    password = "correct horse battery " * 5
    encoded = hash_password(password)
    assert encoded.startswith("$2b$")
    assert verify_password(password, encoded)
    assert not verify_password(password + "!", encoded)


def test_openapi_documents_authentication_and_authorization_errors():
    schema = app.openapi()
    assert "401" in schema["paths"]["/auth/me"]["get"]["responses"]
    assert "403" in schema["paths"]["/admin/health"]["get"]["responses"]


def test_audit_records_authenticated_actor(client: TestClient):
    token = token_for(client, "analyst@example.com")
    correlation_id = "customer-journey-42"
    response = client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Correlation-ID": correlation_id,
        },
    )
    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == correlation_id
    with app.state.audit_session_factory() as db:
        event = (
            db.query(AuditEvent)
            .filter(AuditEvent.path == "/auth/me")
            .order_by(AuditEvent.id.desc())
            .first()
        )
        assert event is not None
        assert event.actor_id == 2
        assert event.status_code == 200
        assert event.correlation_id == correlation_id
    trace = client.get(
        f"/audit/trace/{correlation_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace.status_code == 200
    assert any(event["path"] == "/auth/me" for event in trace.json())


def test_customer_seed_and_search_require_authentication(client: TestClient):
    admin_token = token_for(client, "admin@example.com")
    seed = client.post(
        "/customers/seed", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert seed.status_code == 201
    analyst_token = token_for(client, "analyst@example.com")
    response = client.get(
        "/customers?q=Budi", headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert response.status_code == 200
    assert [customer["customer_code"] for customer in response.json()] == ["CUST-1001"]
    assert client.get("/customers").status_code == 401
    customer_id = response.json()[0]["id"]
    provenance = client.get(
        f"/customers/{customer_id}/provenance",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert provenance.status_code == 200
    assert provenance.json()["source"] == "core.customers"
    assert provenance.json()["audit"][0]["event_type"] == "customer.seeded"


def test_campaign_launch_enqueues_simulated_batch_job(client: TestClient, monkeypatch):
    token = token_for(client, "campaign@example.com")
    correlation_id = "campaign-lifecycle-2026-10"
    create_headers = {
        "Authorization": f"Bearer {token}",
        "X-Correlation-ID": correlation_id,
    }
    headers = {"Authorization": f"Bearer {token}"}
    monitoring = client.get("/monitoring/dashboard", headers=headers)
    assert monitoring.status_code == 200
    assert monitoring.json()["audit"] == []
    created = client.post(
        "/campaigns",
        headers=create_headers,
        json={
            "name": "October return",
            "target_segment": "Enterprise VIP",
            "channel": "email_sim",
            "message_draft": "A considered offer for your next visit.",
        },
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]
    assert created.json()["status"] == "Draft"
    submitted = client.post(
        f"/campaigns/{campaign_id}/request-approval", headers=headers
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "PendingApproval"
    assert (
        client.post(f"/campaigns/{campaign_id}/launch", headers=headers).status_code
        == 409
    )
    analyst_headers = {
        "Authorization": f"Bearer {token_for(client, 'analyst@example.com')}",
    }
    assert (
        client.post(
            f"/campaigns/{campaign_id}/approve", headers=analyst_headers
        ).status_code
        == 403
    )
    approved = client.post(f"/campaigns/{campaign_id}/approve", headers=headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "Approved"
    launched = client.post(f"/campaigns/{campaign_id}/launch", headers=headers)
    assert launched.status_code == 200
    assert launched.json()["status"] == "Active"
    monkeypatch.setattr(worker_tasks, "SessionLocal", app.state.audit_session_factory)
    with app.state.audit_session_factory() as db:
        job = db.query(BatchJob).filter(BatchJob.kind == "campaign_execution").one()
        assert job.payload["channel_simulator"] is True
        assert job.status == "queued"
        assert db.query(Campaign).count() == 1
        assert db.query(Customer).count() == 0
    assert process_one(app.state.audit_session_factory)
    with app.state.audit_session_factory() as db:
        job = db.query(BatchJob).filter(BatchJob.kind == "campaign_execution").one()
        assert job.status == "completed"
        assert job.result["delivery_mode"] == "simulated"
        assert job.result["external_delivery"] is False
        trace = (
            db.query(AuditEvent)
            .filter(AuditEvent.correlation_id == correlation_id)
            .all()
        )
        assert {event.event_type for event in trace} >= {
            "campaign.created",
            "campaign.submitted_for_approval",
            "campaign.approved",
            "campaign.launched",
            "batch.started",
            "batch.completed",
        }
    decision_headers = {
        "Authorization": f"Bearer {token_for(client, 'analyst@example.com')}"
    }
    reconstructed = client.get(
        f"/audit/decision-trace/{correlation_id}", headers=decision_headers
    )
    assert reconstructed.status_code == 200
    assert len(reconstructed.json()["audit_events"]) >= 7


def test_identity_manual_review_requires_reviewer_role(client: TestClient):
    operator = Role(name="operator")
    with app.state.audit_session_factory() as db:
        db.add(operator)
        db.flush()
        db.add(
            User(
                email="operator@example.com",
                password_hash=hash_password("correct-horse-battery"),
                roles=[operator],
            )
        )
        db.commit()
    operator_token = token_for(client, "operator@example.com")
    headers = {"Authorization": f"Bearer {operator_token}"}
    queued = client.post(
        "/identity-reviews",
        headers=headers,
        json={
            "subject_reference": "CRM-88",
            "candidate_references": ["POS-14"],
            "confidence": 0.74,
            "reason": "Same phone number, conflicting member records",
        },
    )
    assert queued.status_code == 201
    review_id = queued.json()["id"]
    assert (
        client.get("/identity-reviews", headers=headers).json()[0]["status"]
        == "pending"
    )
    analyst_headers = {
        "Authorization": f"Bearer {token_for(client, 'analyst@example.com')}"
    }
    decided = client.post(
        f"/identity-reviews/{review_id}/decision",
        headers=analyst_headers,
        json={"decision": "merge", "note": "Same verified phone and member record"},
    )
    assert decided.status_code == 200
    assert decided.json()["decision"] == "merge"


def test_nba_override_and_monitoring_dashboard(client: TestClient):
    admin_headers = {
        "Authorization": f"Bearer {token_for(client, 'admin@example.com')}"
    }
    client.post("/customers/seed", headers=admin_headers)
    correlation_id = "nba-human-override-4821"
    request_headers = {**admin_headers, "X-Correlation-ID": correlation_id}
    recommendation = client.post(
        "/decisions/next-best-actions",
        headers=request_headers,
        json={
            "customer_id": 1,
            "recommended_action": "Send welcome offer",
            "rationale": {"score": 0.82},
        },
    )
    assert recommendation.status_code == 201
    campaign_headers = {
        "Authorization": f"Bearer {token_for(client, 'campaign@example.com')}"
    }
    override = client.post(
        f"/decisions/next-best-actions/{recommendation.json()['id']}/override",
        headers=campaign_headers,
        json={
            "selected_action": "Offer a service consultation",
            "reason": "Customer requested advice instead",
        },
    )
    assert override.status_code == 200
    decision_headers = {
        "Authorization": f"Bearer {token_for(client, 'analyst@example.com')}"
    }
    trace = client.get(
        f"/audit/decision-trace/{correlation_id}", headers=decision_headers
    )
    assert trace.status_code == 200
    assert [item["trigger_event"] for item in trace.json()["decision_steps"]] == [
        "nba.recommended",
        "nba.human_override",
    ]
    with app.state.audit_session_factory() as db:
        assert db.query(HumanOverride).count() == 1
        assert db.query(DecisionTrace).count() == 2
        linked_events = (
            db.query(AuditEvent)
            .filter(AuditEvent.correlation_id == correlation_id)
            .all()
        )
        assert any(event.event_type == "nba.human_override" for event in linked_events)
    drift = client.post(
        "/monitoring/drift",
        headers=admin_headers,
        json={
            "model_name": "retention-v1",
            "metric_name": "psi",
            "metric_value": 0.31,
            "threshold": 0.2,
        },
    )
    assert drift.status_code == 201
    dashboard = client.get("/monitoring/dashboard", headers=admin_headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["drift"][0]["status"] == "drift"
    assert dashboard.json()["audit"]


def test_governance_reconstruction_uses_persisted_decision_trace(client: TestClient):
    admin_token = token_for(client, "admin@example.com")
    correlation_id = "why-did-this-happen-29"
    headers = {
        "Authorization": f"Bearer {admin_token}",
        "X-Correlation-ID": correlation_id,
    }
    client.post("/customers/seed", headers=headers)
    created = client.post(
        "/decisions/next-best-actions",
        headers=headers,
        json={
            "customer_id": 1,
            "recommended_action": "Book a service consultation",
            "rationale": {"affinity": 0.82, "last_visit_days": 42},
        },
    )
    assert created.status_code == 201
    analyst_headers = {
        "Authorization": f"Bearer {token_for(client, 'analyst@example.com')}"
    }
    response = client.get(
        f"/governance/reconstruct/{correlation_id}", headers=analyst_headers
    )
    assert response.status_code == 200
    result = response.json()
    assert result["decision_output"]["action"] == "Book a service consultation"
    assert result["model_inputs"]["rationale"]["affinity"] == 0.82
    assert result["audit_events"]
    assert result["reconstructed_in_seconds"] < 300
