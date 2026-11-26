from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.decision_inputs import (
    load_approved_customer_golden_refs,
    load_contact_history,
    load_serving_score_row,
)
from api.models import Customer, DecisionTrace, NBADecision, User
from api.security import require_roles
from services.decision.nba.serving import evaluate_customer

router = APIRouter(prefix="/decisions", tags=["next best action"])


class DecisionEvaluationRequest(BaseModel):
    customer_id: int = Field(ge=1, le=2_147_483_647, strict=True)

    @field_validator("customer_id", mode="before")
    @classmethod
    def reject_boolean_customer_id(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("customer_id must be an integer, not a boolean")
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value


@router.get("/next-best-actions")
def list_decisions(
    customer_id: int | None = Query(default=None, ge=1, le=2_147_483_647),
    status: str = Query(
        default="proposed", pattern="^(proposed|overridden|accepted|all)$"
    ),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> list[dict]:
    query = (
        db.query(NBADecision)
        .join(Customer, Customer.id == NBADecision.customer_id)
        .filter(Customer.is_demo.is_(False))
    )
    if customer_id is not None:
        query = query.filter(NBADecision.customer_id == customer_id)
    if status != "all":
        query = query.filter(NBADecision.status == status)
    return [
        {
            "id": item.id,
            "customer_id": item.customer_id,
            "recommended_action": item.recommended_action,
            "rationale": item.rationale,
            "status": item.status,
            "selected_action": item.selected_action,
            "created_at": item.created_at,
        }
        for item in query.order_by(NBADecision.created_at.desc()).limit(limit).all()
    ]


@router.post("/next-best-actions/evaluate", status_code=201)
def evaluate_customer_next_best_action(
    payload: DecisionEvaluationRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "analyst")),
) -> dict[str, object]:
    customer = (
        db.query(Customer)
        .filter(Customer.id == payload.customer_id, Customer.is_demo.is_(False))
        .first()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    identity_ref = load_approved_customer_golden_refs(db, [customer]).get(customer.id)
    if identity_ref is None:
        raise HTTPException(
            status_code=409,
            detail="Customer requires an exact, approved Golden Customer mapping.",
        )
    score_row = load_serving_score_row(db, identity_ref)
    output = evaluate_customer(
        customer_ref=identity_ref,
        correlation_id=request.state.correlation_id,
        score_row=score_row,
        consent_doc=None,
        complaint_tickets=None,
        contact_history=load_contact_history(
            db, customer_db_id=customer.id, customer_ref=identity_ref
        ),
        eligibility=None,
        product_suitability=None,
        score_explanation=(
            score_row.get("score_explanation") if score_row is not None else None
        ),
    )
    decision = NBADecision(**output.to_nba_decision_row(customer_db_id=customer.id))
    db.add(decision)
    db.flush()
    record_audit_event(
        db,
        correlation_id=request.state.correlation_id,
        event_type="nba.engine_evaluated",
        actor_id=actor.id,
        entity_type="customer",
        entity_id=customer.id,
        details=output.to_audit_details(decision_id=decision.id),
    )
    db.add(DecisionTrace(**output.to_trace_row(customer_code=customer.customer_code)))
    db.commit()
    return output.to_api_response(decision_id=decision.id, status=decision.status)
