"""Auth/RBAC + Golden Customer serving contract (never use demo core customers)."""

import os
from datetime import datetime, timezone

os.environ["JWT_SECRET"] = "test-only-secret-that-is-long-enough-for-hmac"
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import SQLITE_SCHEMA_TRANSLATE_MAP, Base, get_db
from api.main import app
from api.models import (
    GoldenCustomer,
    ProfileSnapshot,
    RFMLifecycleSnapshot,
    Role,
    User,
)
from api.security import hash_password


@pytest.fixture
def golden_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    ).execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        admin_role = Role(name="admin")
        manager_role = Role(name="campaign_manager")
        db.add_all([admin_role, manager_role])
        db.flush()
        db.add_all(
            [
                User(
                    email="admin@example.com",
                    password_hash=hash_password("correct-horse-battery"),
                    roles=[admin_role],
                ),
                User(
                    email="manager@example.com",
                    password_hash=hash_password("correct-horse-battery"),
                    roles=[manager_role],
                ),
                GoldenCustomer(
                    golden_customer_id="golden-1",
                    first_source_batch_id="batch-1",
                    anchor_source_id="source-1",
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                ProfileSnapshot(
                    golden_customer_id="golden-1",
                    cutoff_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
                    identity_registry_version="v1",
                    source_batch_id="batch-1",
                    rule_version="c360-v1",
                    identity_status="PROVISIONAL",
                    source_identity_count=1,
                    first_join_date=datetime(2026, 1, 1).date(),
                    transaction_count=5,
                    retained_revenue=1000000,
                    visit_count=2,
                    renewal_count=0,
                ),
                RFMLifecycleSnapshot(
                    golden_customer_id="golden-1",
                    cutoff_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
                    identity_registry_version="v1",
                    source_batch_id="batch-1",
                    rule_version="rfm-proposed-v1",
                    identity_status="PROVISIONAL",
                    frequency=5,
                    monetary=1000000,
                    r_score=4,
                    f_score=4,
                    m_score=4,
                    rfm_code="444",
                    tenure_days=200,
                    transactions_60d=1,
                    transactions_90d=2,
                    revenue_90d=1000000,
                    lifecycle="LOYAL",
                ),
            ]
        )

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.state.audit_session_factory = factory
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    del app.state.audit_session_factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _headers(client: TestClient, email: str):
    login = client.post(
        "/auth/login", json={"email": email, "password": "correct-horse-battery"}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_golden_list_requires_auth_and_keeps_legacy_untouched(golden_client):
    assert golden_client.get("/customers/golden").status_code == 401
    admin = _headers(golden_client, "admin@example.com")
    response = golden_client.get("/customers/golden", headers=admin)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["golden_customer_id"] == "golden-1"
    assert rows[0]["retained_revenue"] == 1000000
    assert rows[0]["lifecycle"] == "LOYAL"
    assert rows[0]["identity_status"] == "PROVISIONAL"
    assert "email" not in rows[0]
    assert golden_client.get("/customers", headers=admin).json() == []


def test_golden_provenance_restricted_to_audit_roles(golden_client):
    manager = _headers(golden_client, "manager@example.com")
    assert golden_client.get("/customers/golden", headers=manager).status_code == 200
    assert (
        golden_client.get(
            "/customers/golden/golden-1/provenance", headers=manager
        ).status_code
        == 403
    )
    admin = _headers(golden_client, "admin@example.com")
    response = golden_client.get("/customers/golden/golden-1/provenance", headers=admin)
    assert response.status_code == 200
    assert response.json()["snapshot"]["identity_registry_version"] == "v1"
    assert response.json()["source"] == "customer360.profile_snapshots"
    assert golden_client.get("/customers/golden/none", headers=admin).status_code == 404


def test_golden_route_precedes_generic_customer_route(golden_client):
    """The Golden Customer endpoint must win over the generic ID route."""
    from api.customers import router as customer_router
    from api.golden_customers import router as golden_router

    assert "/customers/golden" in [r.path for r in golden_router.routes]
    assert "/customers/{customer_id}" in [r.path for r in customer_router.routes]

    headers = _headers(golden_client, "admin@example.com")
    response = golden_client.get("/customers/golden", headers=headers)

    assert response.status_code == 200
    assert response.json()[0]["golden_customer_id"] == "golden-1"
