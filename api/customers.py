from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import AuditEvent, Customer, CustomerFeature, DecisionTrace, User
from api.security import require_roles

router = APIRouter(prefix="/customers", tags=["customer 360"])


class CustomerResponse(BaseModel):
    id: int
    customer_code: str
    full_name: str
    email: EmailStr
    segment: str
    ltv: float
    churn_risk: str
    next_best_action: str | None
    created_at: datetime


class CustomerCreate(BaseModel):
    customer_code: str
    full_name: str
    email: EmailStr
    segment: str
    ltv: float = 0.0
    churn_risk: str = "Low"
    next_best_action: str | None = None


@router.get("", response_model=list[CustomerResponse])
def list_customers(
    q: str | None = None,
    segment: str | None = None,
    churn_risk: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> list[Customer]:
    query = db.query(Customer)
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


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> Customer:
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.post("/seed", status_code=status.HTTP_201_CREATED)
def seed_customers(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    if db.query(Customer).first() is not None:
        return {"message": "Customers already seeded"}

    demo_customers = [
        Customer(
            customer_code="CUST-1001",
            full_name="Budi Santoso",
            email="budi.santoso@example.com",
            segment="Enterprise VIP",
            ltv=12450.00,
            churn_risk="Low",
            next_best_action="Tawarkan Upgrade Paket Tahunan dengan Diskon 15%",
        ),
        Customer(
            customer_code="CUST-1002",
            full_name="Siti Rahmawati",
            email="siti.rahma@example.com",
            segment="High Risk Churn",
            ltv=3200.50,
            churn_risk="High",
            next_best_action="Kirimkan Campaign Retensi & Voucher Loyalitas 20%",
        ),
        Customer(
            customer_code="CUST-1003",
            full_name="Dewi Lestari",
            email="dewi.l@example.com",
            segment="SMB Growth",
            ltv=8900.00,
            churn_risk="Medium",
            next_best_action="Jadwalkan Demo Modul Automated Campaign Builder",
        ),
        Customer(
            customer_code="CUST-1004",
            full_name="Ahmad Hidayat",
            email="ahmad.h@example.com",
            segment="High Risk Churn",
            ltv=1500.00,
            churn_risk="High",
            next_best_action="Kirim Push Notification Penawaran Win-Back Khusus",
        ),
        Customer(
            customer_code="CUST-1005",
            full_name="Reza Pratama",
            email="reza.p@example.com",
            segment="Enterprise VIP",
            ltv=45000.00,
            churn_risk="Low",
            next_best_action="Undang ke VIP Customer Roundtable Q4",
        ),
    ]
    db.add_all(demo_customers)
    db.flush()
    for customer in demo_customers:
        record_audit_event(
            db,
            correlation_id=request.state.correlation_id,
            event_type="customer.seeded",
            actor_id=_.id,
            entity_type="customer",
            entity_id=customer.id,
            details={"customer_code": customer.customer_code},
        )
    db.commit()
    return {"message": f"Successfully seeded {len(demo_customers)} customers"}


@router.get("/{customer_id}/provenance")
def customer_provenance(
    customer_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> dict:
    customer = db.get(Customer, customer_id)
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
