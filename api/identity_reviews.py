from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import IdentityReview, User
from api.security import require_roles

router = APIRouter(prefix="/identity-reviews", tags=["identity manual review"])


class IdentityReviewCreate(BaseModel):
    subject_reference: str = Field(min_length=1, max_length=128)
    candidate_references: list[str] = Field(min_length=1, max_length=20)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=5, max_length=256)


class IdentityReviewDecision(BaseModel):
    decision: Literal["merge", "keep_separate"]
    note: str | None = Field(default=None, max_length=1000)


@router.get("", response_model=list[dict])
def list_reviews(
    status: str = Query(default="pending", pattern="^(pending|resolved|all)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "analyst", "operator")),
) -> list[dict]:
    query = db.query(IdentityReview)
    if status != "all":
        query = query.filter(IdentityReview.status == status)
    reviews = query.order_by(IdentityReview.created_at.asc()).limit(limit).all()
    return [
        {
            "id": review.id,
            "subject_reference": review.subject_reference,
            "candidate_references": review.candidate_references,
            "confidence": review.confidence,
            "status": review.status,
            "created_at": review.created_at,
        }
        for review in reviews
    ]


@router.post("", status_code=201)
def enqueue_review(
    payload: IdentityReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "operator")),
) -> dict[str, int | str]:
    review = IdentityReview(
        correlation_id=request.state.correlation_id,
        customer_code=payload.subject_reference[:32],
        full_name=payload.subject_reference[:128],
        flagged_reason=payload.reason,
        match_confidence=payload.confidence,
        subject_reference=payload.subject_reference,
        candidate_references=payload.candidate_references,
        confidence=payload.confidence,
        status="pending",
    )
    db.add(review)
    db.flush()
    record_audit_event(
        db,
        correlation_id=review.correlation_id or request.state.correlation_id,
        event_type="identity.review_queued",
        actor_id=actor.id,
        entity_type="identity_review",
        entity_id=review.id,
        details={"subject_reference": review.subject_reference},
    )
    db.commit()
    return {"id": review.id, "status": review.status}


@router.post("/{review_id}/decision")
def decide_review(
    review_id: int,
    payload: IdentityReviewDecision,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "analyst")),
) -> dict[str, int | str]:
    review = db.get(IdentityReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Identity review not found")
    if review.status != "pending":
        raise HTTPException(
            status_code=409, detail="Identity review is already resolved"
        )
    review.status = "resolved"
    review.decision = payload.decision
    review.reviewer_id = actor.id
    review.review_note = payload.note
    review.reviewed_at = datetime.now(timezone.utc)
    record_audit_event(
        db,
        correlation_id=review.correlation_id or request.state.correlation_id,
        event_type="identity.review_decided",
        actor_id=actor.id,
        entity_type="identity_review",
        entity_id=review.id,
        details={"decision": payload.decision, "note": payload.note},
    )
    db.commit()
    return {"id": review.id, "status": review.status, "decision": review.decision}
