from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import Customer, DecisionTrace, HumanOverride, NBADecision, User
from api.security import require_roles

router = APIRouter(prefix="/decisions", tags=["next best action"])


class RecommendationCreate(BaseModel):
    customer_id: int
    recommended_action: str = Field(min_length=2, max_length=256)
    rationale: dict = Field(default_factory=dict)


class OverrideCreate(BaseModel):
    selected_action: str = Field(min_length=2, max_length=256)
    reason: str = Field(min_length=5, max_length=1000)


@router.get("/next-best-actions")
def list_decisions(
    customer_id: int | None = None,
    status: str = Query(
        default="proposed", pattern="^(proposed|overridden|accepted|all)$"
    ),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> list[dict]:
    query = db.query(NBADecision)
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
    customer = db.get(Customer, payload.customer_id)
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


@router.post("/next-best-actions/{decision_id}/override")
def override_decision(
    decision_id: int,
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
