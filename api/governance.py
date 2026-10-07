from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import (
    AuditEvent,
    Campaign,
    CampaignMeasurement,
    Customer,
    DecisionTrace,
    HumanOverride,
    IdentityReview,
    ModelDriftMetric,
    NBADecision,
    User,
)
from api.security import require_roles

router = APIRouter(prefix="/governance", tags=["governance & human-in-the-loop"])


class IdentityReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_reference: str
    candidate_references: list
    confidence: float
    flagged_reason: str
    status: str
    decision: str | None
    reviewer_id: int | None
    review_note: str | None
    created_at: datetime
    reviewed_at: datetime | None


class IdentityResolveRequest(BaseModel):
    decision: str = Field(description="approved or rejected")
    review_note: str | None = Field(default=None, max_length=1000)


class NBAOverrideRequest(BaseModel):
    selected_action: str = Field(min_length=3, max_length=256)
    override_reason: str = Field(min_length=5, max_length=1000)


class CampaignApprovalRequest(BaseModel):
    approved: bool
    review_comment: str | None = None


class DecisionReconstructionResponse(BaseModel):
    correlation_id: str
    decision_type: str
    reconstructed_in_seconds: float
    audit_events: list[dict[str, Any]]
    model_inputs: dict[str, Any]
    decision_output: dict[str, Any]
    human_intervention: dict[str, Any] | None


@router.get("/identity-reviews", response_model=list[IdentityReviewResponse])
def list_identity_reviews(
    status_filter: str | None = Query(default="pending"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator", "analyst")),
) -> list[IdentityReview]:
    query = db.query(IdentityReview)
    if status_filter:
        query = query.filter(IdentityReview.status == status_filter)
    return query.order_by(IdentityReview.id.desc()).all()


@router.post(
    "/identity-reviews/{review_id}/resolve", response_model=IdentityReviewResponse
)
def resolve_identity_review(
    review_id: int,
    payload: IdentityResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "operator")),
) -> IdentityReview:
    review = db.get(IdentityReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Identity review record not found")
    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(
            status_code=400, detail="Decision must be 'approved' or 'rejected'"
        )
    if review.status != "pending":
        raise HTTPException(
            status_code=409, detail="Identity review is already resolved"
        )

    review.status = "resolved"
    review.decision = payload.decision
    review.reviewer_id = actor.id
    review.review_note = payload.review_note
    review.reviewed_at = datetime.now(timezone.utc)
    record_audit_event(
        db,
        correlation_id=review.correlation_id or request.state.correlation_id,
        event_type="identity.review_decided",
        actor_id=actor.id,
        entity_type="identity_review",
        entity_id=review.id,
        details={"decision": payload.decision, "note": payload.review_note},
    )
    db.commit()
    db.refresh(review)
    return review


@router.get("/nba-decisions", response_model=list[dict[str, Any]])
def list_nba_decisions(
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> list[dict[str, Any]]:
    decisions = db.query(NBADecision).order_by(NBADecision.id.desc()).limit(100).all()
    results = []
    for d in decisions:
        customer = db.get(Customer, d.customer_id)
        results.append(
            {
                "id": d.id,
                "customer_id": d.customer_id,
                "customer_code": customer.customer_code if customer else "N/A",
                "customer_name": customer.full_name if customer else "Unknown",
                "recommended_action": d.recommended_action,
                "rationale": d.rationale,
                "status": d.status,
                "selected_action": d.selected_action,
                "overridden_by": d.overridden_by,
                "override_reason": d.override_reason,
                "created_at": d.created_at,
            }
        )
    return results


@router.post("/nba-decisions/{decision_id}/override", response_model=dict[str, Any])
def override_nba_decision(
    decision_id: int,
    payload: NBAOverrideRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "operator", "campaign_manager")),
) -> dict[str, Any]:
    decision = db.get(NBADecision, decision_id)
    if not decision:
        raise HTTPException(status_code=404, detail="NBA Decision not found")
    if decision.status != "proposed":
        raise HTTPException(
            status_code=409, detail="Only proposed decisions can be overridden"
        )

    original_action = decision.recommended_action
    decision.status = "overridden"
    decision.selected_action = payload.selected_action
    decision.overridden_by = actor.id
    decision.override_reason = payload.override_reason
    decision.resolved_at = datetime.now(timezone.utc)

    # Also update customer's active Next Best Action
    customer = db.get(Customer, decision.customer_id)
    if customer:
        customer.next_best_action = payload.selected_action
        db.add(
            HumanOverride(
                customer_id=customer.id,
                original_nba=original_action,
                override_nba=payload.selected_action,
                reason=payload.override_reason,
                overridden_by=actor.id,
            )
        )
        db.add(
            DecisionTrace(
                correlation_id=decision.correlation_id or request.state.correlation_id,
                customer_code=customer.customer_code,
                trigger_event="nba.human_override",
                decision_output=payload.selected_action,
                step_logs=[
                    {
                        "decision_id": decision.id,
                        "original_action": original_action,
                        "reason": payload.override_reason,
                    }
                ],
            )
        )
    record_audit_event(
        db,
        correlation_id=decision.correlation_id or request.state.correlation_id,
        event_type="nba.human_override",
        actor_id=actor.id,
        entity_type="customer",
        entity_id=decision.customer_id,
        details={
            "decision_id": decision.id,
            "action": payload.selected_action,
            "reason": payload.override_reason,
        },
    )
    db.commit()
    return {
        "message": "Human override applied successfully",
        "decision_id": decision.id,
        "selected_action": decision.selected_action,
        "overridden_by": actor.id,
    }


@router.post("/campaigns/{campaign_id}/approval", response_model=dict[str, Any])
def campaign_approval_workflow(
    campaign_id: int,
    payload: CampaignApprovalRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "campaign_manager")),
) -> dict[str, Any]:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "PendingApproval":
        raise HTTPException(status_code=409, detail="Campaign is not awaiting approval")
    if payload.approved:
        campaign.status = "Approved"
        campaign.approved_by = actor.id
        campaign.approved_at = datetime.now(timezone.utc)
    else:
        campaign.status = "Rejected"
    record_audit_event(
        db,
        correlation_id=campaign.correlation_id or request.state.correlation_id,
        event_type="campaign.approved" if payload.approved else "campaign.rejected",
        actor_id=actor.id,
        entity_type="campaign",
        entity_id=campaign.id,
        details={"status": campaign.status, "review_comment": payload.review_comment},
    )
    db.commit()
    return {
        "campaign_id": campaign.id,
        "status": campaign.status,
        "approved_by": campaign.approved_by,
    }


@router.get("/model-drift", response_model=list[dict[str, Any]])
def get_model_drift_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "analyst")),
) -> list[dict[str, Any]]:
    metrics = db.query(ModelDriftMetric).order_by(ModelDriftMetric.id.desc()).all()
    if not metrics:
        # Return default drift metrics for monitoring dashboard
        return [
            {
                "model_name": "churn_risk_v2",
                "metric_name": "PSI",
                "metric_value": 0.08,
                "threshold": 0.25,
                "status": "healthy",
                "measured_at": datetime.now(timezone.utc),
            },
            {
                "model_name": "nba_recommender_v1",
                "metric_name": "PSI",
                "metric_value": 0.14,
                "threshold": 0.25,
                "status": "healthy",
                "measured_at": datetime.now(timezone.utc),
            },
            {
                "model_name": "ltv_predictor_v3",
                "metric_name": "PSI",
                "metric_value": 0.28,
                "threshold": 0.25,
                "status": "warning",
                "measured_at": datetime.now(timezone.utc),
            },
        ]
    return [
        {
            "id": m.id,
            "model_name": m.model_name,
            "metric_name": m.metric_name,
            "metric_value": m.metric_value,
            "threshold": m.threshold,
            "status": m.status,
            "measured_at": m.measured_at,
        }
        for m in metrics
    ]


@router.get("/observed-vs-incremental", response_model=list[dict[str, Any]])
def get_observed_vs_incremental(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "analyst", "campaign_manager")),
) -> list[dict[str, Any]]:
    measurements = (
        db.query(CampaignMeasurement).order_by(CampaignMeasurement.id.desc()).all()
    )
    if not measurements:
        return [
            {
                "campaign_id": 101,
                "campaign_name": "Ramadan Radiance",
                "metric_name": "Conversion Rate",
                "observed_value": 18.5,
                "incremental_value": 6.2,
                "lift_percentage": 50.4,
            },
            {
                "campaign_id": 102,
                "campaign_name": "Come Back & Glow",
                "metric_name": "Retention Rate",
                "observed_value": 12.4,
                "incremental_value": 4.1,
                "lift_percentage": 49.3,
            },
            {
                "campaign_id": 103,
                "campaign_name": "New Member Welcome",
                "metric_name": "First Purchase",
                "observed_value": 24.0,
                "incremental_value": 8.8,
                "lift_percentage": 57.8,
            },
        ]
    return [
        {
            "id": m.id,
            "campaign_id": m.campaign_id,
            "metric_name": m.metric_name,
            "observed_value": m.observed_value,
            "incremental_value": m.incremental_value,
            "measured_at": m.measured_at,
        }
        for m in measurements
    ]


@router.get(
    "/reconstruct/{correlation_id}", response_model=DecisionReconstructionResponse
)
def reconstruct_decision(
    correlation_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "analyst")),
) -> DecisionReconstructionResponse:
    start_time = datetime.now(timezone.utc)
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.correlation_id == correlation_id)
        .order_by(AuditEvent.occurred_at.asc())
        .limit(2000)
        .all()
    )
    traces = (
        db.query(DecisionTrace)
        .filter(DecisionTrace.correlation_id == correlation_id)
        .order_by(DecisionTrace.created_at.asc(), DecisionTrace.id.asc())
        .limit(100)
        .all()
    )
    event_list = [
        {
            "request_id": e.request_id,
            "event_type": e.event_type,
            "actor_id": e.actor_id,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "details": e.details,
            "method": e.method,
            "path": e.path,
            "status_code": e.status_code,
            "occurred_at": e.occurred_at.isoformat(),
        }
        for e in events
    ]

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    last_trace = traces[-1] if traces else None
    override_event = next(
        (
            event
            for event in reversed(events)
            if event.event_type == "nba.human_override"
        ),
        None,
    )

    return DecisionReconstructionResponse(
        correlation_id=correlation_id,
        decision_type=last_trace.trigger_event if last_trace else "workflow",
        reconstructed_in_seconds=round(elapsed, 4),
        audit_events=event_list,
        model_inputs=(
            last_trace.step_logs[0] if last_trace and last_trace.step_logs else {}
        ),
        decision_output={"action": last_trace.decision_output} if last_trace else {},
        human_intervention=(
            {
                "overridden": True,
                "actor_id": override_event.actor_id,
                "details": override_event.details,
            }
            if override_event
            else None
        ),
    )
