from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import (
    AuditEvent,
    Customer,
    CustomerFeature,
    DecisionTrace,
    GoldenCustomer,
    ProfileSnapshot,
    SourceIdentityMapping,
    User,
)
from api.security import require_roles
from api.validation import DBId, email_field

router = APIRouter(prefix="/customers", tags=["customer 360"])


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_code: str
    full_name: str
    email: EmailStr
    segment: str
    ltv: float | None
    churn_risk: str | None
    next_best_action: str | None
    golden_customer_id: str | None
    created_at: datetime


class CustomerCreate(BaseModel):
    customer_code: str = Field(min_length=1, max_length=32, pattern=r"^[^\x00]*$")
    full_name: str = Field(min_length=1, max_length=128, pattern=r"^[^\x00]*$")
    email: EmailStr = email_field()
    segment: str = Field(min_length=1, max_length=64, pattern=r"^[^\x00]*$")


class GoldenIdentityLinkRequest(BaseModel):
    golden_customer_id: str = Field(
        min_length=36, max_length=36, pattern=r"^[0-9a-fA-F-]{36}$"
    )


@router.get("", response_model=list[CustomerResponse])
def list_customers(
    q: str | None = Query(default=None, pattern=r"^[^\x00]*$"),
    segment: str | None = Query(default=None, pattern=r"^[^\x00]*$"),
    churn_risk: str | None = Query(default=None, pattern=r"^[^\x00]*$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> list[Customer]:
    query = db.query(Customer).filter(Customer.is_demo.is_(False))
    if q:
        search_pattern = f"%{q}%"
        query = query.filter(
            (Customer.full_name.ilike(search_pattern))
            | (Customer.customer_code.ilike(search_pattern))
            | (Customer.email.ilike(search_pattern))
        )
    if segment:
        query = query.filter(Customer.segment == segment)
    if churn_risk:
        query = query.filter(Customer.churn_risk == churn_risk)
    return query.order_by(Customer.id.desc()).limit(limit).all()


@router.get("/seed", include_in_schema=False)
def reject_unsupported_seed_get() -> Response:
    # Static POST-only path must take priority over parameterized GET.
    return Response(status_code=405, headers={"Allow": "POST, OPTIONS"})


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: DBId,
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> Customer:
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.is_demo.is_(False))
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.post(
    "/seed",
    status_code=status.HTTP_410_GONE,
    deprecated=True,
)
def disable_demo_seed(_: User = Depends(require_roles("admin"))) -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Customer demo seeding has been permanently disabled.",
    )


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
) -> Customer:
    if (
        db.query(Customer)
        .filter(Customer.customer_code == payload.customer_code)
        .first()
    ):
        raise HTTPException(status_code=409, detail="Customer code already exists")
    customer = Customer(**payload.model_dump(), source_type="registered")
    db.add(customer)
    db.flush()
    record_audit_event(
        db,
        correlation_id=request.state.correlation_id,
        event_type="customer.registered",
        actor_id=actor.id,
        entity_type="customer",
        entity_id=customer.id,
        details={
            "customer_code": customer.customer_code,
            "source_type": customer.source_type,
        },
    )
    db.commit()
    db.refresh(customer)
    return customer


@router.put("/{customer_id}/golden-identity")
def link_approved_golden_identity(
    customer_id: DBId,
    payload: GoldenIdentityLinkRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
) -> dict[str, int | str]:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.is_demo:
        raise HTTPException(status_code=404, detail="Customer not found")
    golden = db.get(GoldenCustomer, payload.golden_customer_id)
    if golden is None or golden.status != "APPROVED":
        raise HTTPException(
            status_code=409, detail="Golden Customer identity is not approved"
        )
    exact_source_match = (
        db.query(SourceIdentityMapping)
        .filter(
            SourceIdentityMapping.source_customer_id == customer.customer_code,
            SourceIdentityMapping.golden_customer_id == golden.golden_customer_id,
        )
        .first()
    )
    approved_profile = (
        db.query(ProfileSnapshot.id)
        .filter(ProfileSnapshot.golden_customer_id == golden.golden_customer_id)
        .first()
    )
    if exact_source_match is None or approved_profile is None:
        raise HTTPException(
            status_code=409,
            detail="Customer code must match an approved Golden identity source exactly.",
        )
    other = (
        db.query(Customer)
        .filter(
            Customer.golden_customer_id == golden.golden_customer_id,
            Customer.id != customer.id,
            Customer.is_demo.is_(False),
        )
        .first()
    )
    if other is not None:
        raise HTTPException(status_code=409, detail="Golden identity is already linked")
    if customer.golden_customer_id not in (None, golden.golden_customer_id):
        raise HTTPException(
            status_code=409, detail="Customer already has a different Golden identity"
        )
    customer.golden_customer_id = golden.golden_customer_id
    record_audit_event(
        db,
        correlation_id=request.state.correlation_id,
        event_type="customer.golden_identity_linked",
        actor_id=actor.id,
        entity_type="customer",
        entity_id=customer.id,
        details={
            "golden_customer_id": golden.golden_customer_id,
            "identity_status": golden.status,
        },
    )
    db.commit()
    return {
        "customer_id": customer.id,
        "golden_customer_id": golden.golden_customer_id,
        "status": "linked",
    }


@router.get("/{customer_id}/provenance")
def customer_provenance(
    customer_id: DBId,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> dict:
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.is_demo.is_(False))
        .first()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    features = (
        db.query(CustomerFeature)
        .filter(CustomerFeature.customer_id == customer_id)
        .order_by(CustomerFeature.computed_at.desc())
        .limit(limit)
        .all()
    )
    events = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.entity_type == "customer",
            AuditEvent.entity_id == str(customer_id),
        )
        .order_by(AuditEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )
    decisions = (
        db.query(DecisionTrace)
        .filter(DecisionTrace.customer_code == customer.customer_code)
        .order_by(DecisionTrace.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "customer_id": customer_id,
        "source": "core.customers",
        "features": [
            {
                "feature": feature.feature_name,
                "value": feature.feature_value,
                "computed_at": feature.computed_at,
            }
            for feature in features
        ],
        "audit": [
            {
                "correlation_id": event.correlation_id,
                "event_type": event.event_type,
                "actor_id": event.actor_id,
                "details": event.details,
                "occurred_at": event.occurred_at,
            }
            for event in events
        ],
        "decision_traces": [
            {
                "correlation_id": decision.correlation_id,
                "trigger_event": decision.trigger_event,
                "decision_output": decision.decision_output,
                "steps": decision.step_logs,
                "created_at": decision.created_at,
            }
            for decision in decisions
        ],
    }
