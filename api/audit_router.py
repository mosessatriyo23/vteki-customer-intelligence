from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import AuditEvent, DecisionTrace, User
from api.security import require_roles

router = APIRouter(prefix="/audit", tags=["audit trail"])


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str
    correlation_id: str
    actor_id: int | None
    event_type: str
    entity_type: str | None
    entity_id: str | None
    details: dict
    method: str
    path: str
    status_code: int
    client_ip: str | None
    user_agent: str | None
    occurred_at: datetime


@router.get("/events", response_model=list[AuditEventResponse])
def list_audit_events(
    limit: int = Query(default=50, ge=1, le=500),
    method: str | None = Query(default=None, pattern=r"^[^\x00]*$"),
    status_code: int | None = Query(default=None, ge=100, le=599),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "analyst")),
) -> list[AuditEvent]:
    query = db.query(AuditEvent)
    if method:
        query = query.filter(AuditEvent.method == method.upper())
    if status_code:
        query = query.filter(AuditEvent.status_code == status_code)
    return query.order_by(AuditEvent.id.desc()).limit(limit).all()


@router.get("/trace/{correlation_id}")
def trace_correlation(
    correlation_id: str = Path(pattern=r"^[^\x00]*$"),
    limit: int = Query(default=200, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "analyst")),
) -> dict:
    if len(correlation_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid correlation ID")

    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.correlation_id == correlation_id)
        .order_by(AuditEvent.occurred_at.asc(), AuditEvent.id.asc())
        .limit(limit + 1)
        .all()
    )

    has_more = len(events) > limit
    events = events[:limit]

    return {
        "correlation_id": correlation_id,
        "audit_events": [AuditEventResponse.model_validate(event) for event in events],
        "audit_events_returned": len(events),
        "audit_events_truncated": has_more,
    }


@router.get("/decision-trace/{correlation_id}")
def trace_decision(
    correlation_id: str = Path(pattern=r"^[^\x00]*$"),
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "analyst")),
) -> dict:
    if len(correlation_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid correlation ID")

    decisions = (
        db.query(DecisionTrace)
        .filter(DecisionTrace.correlation_id == correlation_id)
        .order_by(DecisionTrace.created_at.asc(), DecisionTrace.id.asc())
        .limit(limit + 1)
        .all()
    )
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.correlation_id == correlation_id)
        .order_by(AuditEvent.occurred_at.asc(), AuditEvent.id.asc())
        .limit(limit + 1)
        .all()
    )

    decisions_truncated = len(decisions) > limit
    events_truncated = len(events) > limit

    decisions = decisions[:limit]
    events = events[:limit]

    return {
        "correlation_id": correlation_id,
        "decision_steps": [
            {
                "customer_code": item.customer_code,
                "trigger_event": item.trigger_event,
                "decision_output": item.decision_output,
                "steps": item.step_logs,
                "created_at": item.created_at,
            }
            for item in decisions
        ],
        "audit_events": [AuditEventResponse.model_validate(event) for event in events],
        "decision_steps_returned": len(decisions),
        "audit_events_returned": len(events),
        "decision_steps_truncated": decisions_truncated,
        "audit_events_truncated": events_truncated,
    }
