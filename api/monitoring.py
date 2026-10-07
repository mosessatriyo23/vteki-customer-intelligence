from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import (
    AuditEvent,
    CampaignMeasurement,
    ModelDriftMetric,
    PipelineRun,
    User,
)
from api.security import require_roles

router = APIRouter(prefix="/monitoring", tags=["management monitoring"])


class DriftMetricCreate(BaseModel):
    model_name: str = Field(min_length=1, max_length=100)
    metric_name: str = Field(min_length=1, max_length=100)
    metric_value: float
    threshold: float = Field(ge=0)


class MeasurementCreate(BaseModel):
    campaign_id: int
    metric_name: str = Field(min_length=1, max_length=100)
    observed_value: float
    incremental_value: float


@router.get("/dashboard")
def dashboard(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: User = Depends(
        require_roles("admin", "analyst", "operator", "campaign_manager")
    ),
) -> dict:
    drift = (
        db.query(ModelDriftMetric)
        .order_by(ModelDriftMetric.measured_at.desc())
        .limit(limit)
        .all()
    )
    measurements = (
        db.query(CampaignMeasurement)
        .order_by(CampaignMeasurement.measured_at.desc())
        .limit(limit)
        .all()
    )
    actor_roles = {role.name for role in actor.roles}
    can_read_audit = bool(actor_roles.intersection({"admin", "analyst"}))
    audit = (
        db.query(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(limit).all()
        if can_read_audit
        else []
    )
    pipeline_runs = (
        db.query(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(limit).all()
    )
    return {
        "drift": [
            {
                "model": item.model_name,
                "metric": item.metric_name,
                "value": item.metric_value,
                "threshold": item.threshold,
                "status": item.status,
                "measured_at": item.measured_at,
            }
            for item in drift
        ],
        "campaign_measurements": [
            {
                "campaign_id": item.campaign_id,
                "metric": item.metric_name,
                "observed": item.observed_value,
                "incremental": item.incremental_value,
                "measured_at": item.measured_at,
            }
            for item in measurements
        ],
        "audit": [
            {
                "correlation_id": item.correlation_id,
                "event_type": item.event_type,
                "actor_id": item.actor_id,
                "status_code": item.status_code,
                "occurred_at": item.occurred_at,
            }
            for item in audit
        ],
        "pipeline_runs": [
            {
                "id": item.id,
                "status": item.status,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
                "step_results": item.step_results,
                "error_summary": item.error_summary if "operator" in actor_roles else None,
            }
            for item in pipeline_runs
        ],
    }


@router.post("/drift", status_code=201)
def record_drift(
    payload: DriftMetricCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "operator")),
) -> dict[str, int | str]:
    status = "drift" if payload.metric_value > payload.threshold else "healthy"
    metric = ModelDriftMetric(
        model_name=payload.model_name,
        metric_name=payload.metric_name,
        metric_value=payload.metric_value,
        threshold=payload.threshold,
        status=status,
    )
    db.add(metric)
    db.flush()
    record_audit_event(
        db,
        correlation_id=request.state.correlation_id,
        event_type="model.drift_measured",
        actor_id=actor.id,
        entity_type="model",
        entity_id=payload.model_name,
        details={
            "metric": payload.metric_name,
            "value": payload.metric_value,
            "threshold": payload.threshold,
            "status": status,
        },
    )
    db.commit()
    return {"id": metric.id, "status": status}


@router.post("/measurements", status_code=201)
def record_measurement(
    payload: MeasurementCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "analyst")),
) -> dict[str, int | str]:
    measurement = CampaignMeasurement(**payload.model_dump())
    db.add(measurement)
    db.flush()
    record_audit_event(
        db,
        correlation_id=request.state.correlation_id,
        event_type="campaign.measured",
        actor_id=actor.id,
        entity_type="campaign",
        entity_id=measurement.campaign_id,
        details={
            "metric": measurement.metric_name,
            "observed": measurement.observed_value,
            "incremental": measurement.incremental_value,
        },
    )
    db.commit()
    return {"id": measurement.id, "status": "recorded"}
