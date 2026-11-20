from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import Customer, DecisionTrace, HumanOverride, NBADecision, User
from api.security import require_roles
from api.validation import DBId
from services.decision.nba.engine import (
    EligibilityProfile,
    NBAEngine,
    ProductSuitability,
)
from services.decision.policy.suppression import CustomerConsent

router = APIRouter(prefix="/decisions", tags=["next best action"])


class RecommendationCreate(BaseModel):
    customer_id: int = Field(ge=1, le=2_147_483_647)
    recommended_action: str = Field(min_length=2, max_length=256, pattern=r"^[^\x00]*$")
    rationale: dict = Field(default_factory=dict)


class DecisionEvaluationRequest(BaseModel):
    customer_id: int = Field(ge=1, le=2_147_483_647)


class OverrideCreate(BaseModel):
    selected_action: str = Field(min_length=2, max_length=256, pattern=r"^[^\x00]*$")
    reason: str = Field(min_length=5, max_length=512)


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
    query = db.query(NBADecision).join(Customer, Customer.id == NBADecision.customer_id).filter(Customer.is_demo.is_(False))
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


@router.post("/next-best-actions", status_code=201)
def create_decision(
    payload: RecommendationCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "analyst")),
) -> dict[str, int | str]:
    customer = (
        db.query(Customer)
        .filter(Customer.id == payload.customer_id, Customer.is_demo.is_(False))
        .first()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    decision = NBADecision(
        customer_id=customer.id,
        correlation_id=request.state.correlation_id,
        recommended_action=payload.recommended_action,
        rationale=payload.rationale,
        status="proposed",
    )
    db.add(decision)
    db.flush()
    record_audit_event(
        db,
        correlation_id=decision.correlation_id or request.state.correlation_id,
        event_type="nba.recommended",
        actor_id=actor.id,
        entity_type="customer",
        entity_id=customer.id,
        details={
            "decision_id": decision.id,
            "action": decision.recommended_action,
            "rationale": payload.rationale,
        },
    )
    db.add(
        DecisionTrace(
            correlation_id=decision.correlation_id or request.state.correlation_id,
            customer_code=customer.customer_code,
            trigger_event="nba.recommended",
            decision_output=decision.recommended_action,
            step_logs=[{"decision_id": decision.id, "rationale": payload.rationale}],
        )
    )
    db.commit()
    return {"id": decision.id, "status": decision.status}


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

    # Current core and Golden Customer feeds do not include serving-approved
    # scores, K-10 consent, complaint history, contact history, or catalogue
    # availability. Build explicit unknown/empty inputs so Chris's engine
    # evaluates conservatively instead of inferring permission from missing data.
    identity_ref = customer.golden_customer_id or customer.customer_code
    consent = CustomerConsent.from_k10(
        {
            "customer_id": identity_ref,
            "global_consent": {"status": "UNKNOWN"},
            "channels": {},
        }
    )
    eligibility = EligibilityProfile(
        customer_id=identity_ref,
        tenure_days=0,
        membership_days_remaining=0,
        has_active_membership=False,
    )
    record = NBAEngine().decide(
        customer_id=identity_ref,
        ai_scores=None,
        consent=consent,
        complaint_tickets=[],
        contact_history=[],
        eligibility=eligibility,
        product_suitability=ProductSuitability(),
        evaluation_date=datetime.now(timezone.utc),
        correlation_id=request.state.correlation_id,
    )
    result = record.to_dict()
    selected_action = record.selected_action_id
    is_no_action = selected_action == "NO_ACTION"
    decision = NBADecision(
        customer_id=customer.id,
        correlation_id=request.state.correlation_id,
        recommended_action=selected_action,
        rationale={
            "reason": record.rationale_text,
            "engine_version": record.engine_version,
            "expected_value": record.expected_value,
            "no_action_reason": record.no_action_reason,
            "degraded_input": record.degraded_input,
            "serving_ready": False,
            "identity_ref": identity_ref,
            "input_availability": {
                "model_scores": "unavailable; development predictions are not serving-approved",
                "consent": "unknown; K-10 source not connected",
                "complaint_history": "unavailable",
                "contact_history": "unavailable",
                "product_suitability": "unavailable",
            },
            "checks": record.checks,
            "candidates": record.candidates,
        },
        status="accepted" if is_no_action else "proposed",
    )
    db.add(decision)
    db.flush()
    record_audit_event(
        db,
        correlation_id=request.state.correlation_id,
        event_type="nba.engine_evaluated",
        actor_id=actor.id,
        entity_type="customer",
        entity_id=customer.id,
        details={
            "decision_id": decision.id,
            "selected_action": selected_action,
            "engine_version": record.engine_version,
            "degraded_input": record.degraded_input,
            "serving_ready": False,
            "identity_ref": identity_ref,
        },
    )
    db.add(
        DecisionTrace(
            correlation_id=request.state.correlation_id,
            customer_code=customer.customer_code,
            trigger_event="nba.engine_evaluated",
            decision_output=selected_action,
            step_logs=[result],
        )
    )
    db.commit()
    return {
        "id": decision.id,
        "status": decision.status,
        "selected_action": selected_action,
        "reason": record.rationale_text,
        "engine_version": record.engine_version,
        "no_action_reason": record.no_action_reason,
        "degraded_input": record.degraded_input,
        "serving_ready": False,
    }


@router.post("/next-best-actions/{decision_id}/override")
def override_decision(
    decision_id: DBId,
    payload: OverrideCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "campaign_manager")),
) -> dict[str, int | str]:
    decision = db.get(NBADecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if decision.status != "proposed":
        raise HTTPException(
            status_code=409, detail="Only proposed decisions can be overridden"
        )
    decision.status = "overridden"
    decision.selected_action = payload.selected_action
    decision.overridden_by = actor.id
    decision.override_reason = payload.reason
    decision.resolved_at = datetime.now(timezone.utc)
    db.add(
        HumanOverride(
            customer_id=decision.customer_id,
            original_nba=decision.recommended_action,
            override_nba=payload.selected_action,
            reason=payload.reason,
            overridden_by=actor.id,
        )
    )
    customer = db.get(Customer, decision.customer_id)
    record_audit_event(
        db,
        correlation_id=decision.correlation_id or request.state.correlation_id,
        event_type="nba.human_override",
        actor_id=actor.id,
        entity_type="customer",
        entity_id=decision.customer_id,
        details={
            "decision_id": decision.id,
            "selected_action": payload.selected_action,
            "reason": payload.reason,
        },
    )
    if customer is not None:
        db.add(
            DecisionTrace(
                correlation_id=decision.correlation_id or request.state.correlation_id,
                customer_code=customer.customer_code,
                trigger_event="nba.human_override",
                decision_output=payload.selected_action,
                step_logs=[
                    {
                        "decision_id": decision.id,
                        "original_action": decision.recommended_action,
                        "reason": payload.reason,
                        "overridden_by": actor.id,
                    }
                ],
            )
        )
    db.commit()
    return {
        "id": decision.id,
        "status": decision.status,
        "selected_action": decision.selected_action,
    }
