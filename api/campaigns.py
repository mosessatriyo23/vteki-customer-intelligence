from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import (
    BatchJob,
    Campaign,
    CampaignMeasurement,
    Customer,
    NBADecision,
    User,
)
from api.security import require_roles
from api.validation import DBId

router = APIRouter(prefix="/campaigns", tags=["campaign builder"])


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    target_segment: str
    channel: str
    ab_test_ratio: int
    status: str
    message_draft: str | None
    nba_decision_id: int | None = None
    target_customer_id: int | None = None
    approved_by: int | None
    approved_at: datetime | None
    correlation_id: str | None
    created_by: int | None
    created_at: datetime
    latest_execution: dict | None = None
    latest_measurement: dict | None = None


class CampaignCreate(BaseModel):
    name: str = Field(min_length=3, max_length=128, pattern=r"^[^\x00]*$")
    target_segment: str = Field(min_length=2, max_length=64, pattern=r"^[^\x00]*$")
    channel: str = Field(
        min_length=2, max_length=32, pattern=r"^[^\x00]*$"
    )  # email_sim, sms_sim, push_sim
    ab_test_ratio: int = Field(default=50, ge=0, le=100, strict=True)
    message_draft: str | None = Field(
        default=None, max_length=2000, pattern=r"^[^\x00]*$"
    )
    nba_decision_id: int | None = Field(default=None, ge=1, le=2_147_483_647, strict=True)

    @field_validator("ab_test_ratio", mode="before")
    @classmethod
    def normalize_ab_test_ratio(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("ab_test_ratio must be an integer, not a boolean")
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value


@router.get("", response_model=list[CampaignResponse])
def list_campaigns(
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> list[dict]:
    campaigns = db.query(Campaign).order_by(Campaign.id.desc()).all()
    if not campaigns:
        return []

    job_ids = [campaign.execution_job_id for campaign in campaigns if campaign.execution_job_id]
    jobs = db.query(BatchJob).filter(BatchJob.id.in_(job_ids)).all() if job_ids else []
    jobs_by_id = {job.id: job for job in jobs}
    campaign_ids = [campaign.id for campaign in campaigns]
    measurements = (
        db.query(CampaignMeasurement)
        .filter(CampaignMeasurement.campaign_id.in_(campaign_ids))
        .order_by(CampaignMeasurement.measured_at.desc(), CampaignMeasurement.id.desc())
        .all()
        if campaign_ids
        else []
    )
    measurement_by_campaign: dict[int, CampaignMeasurement] = {}
    for measurement in measurements:
        measurement_by_campaign.setdefault(measurement.campaign_id, measurement)

    response = []
    for campaign in campaigns:
        job = jobs_by_id.get(campaign.execution_job_id)
        response.append(
            {
                "id": campaign.id,
                "name": campaign.name,
                "target_segment": campaign.target_segment,
                "channel": campaign.channel,
                "ab_test_ratio": campaign.ab_test_ratio,
                "status": campaign.status,
                "message_draft": campaign.message_draft,
                "nba_decision_id": campaign.nba_decision_id,
                "target_customer_id": campaign.target_customer_id,
                "approved_by": campaign.approved_by,
                "approved_at": campaign.approved_at,
                "correlation_id": campaign.correlation_id,
                "created_by": campaign.created_by,
                "created_at": campaign.created_at,
                "latest_execution": (
                    {
                        "job_id": job.id,
                        "status": job.status,
                        "result": job.result,
                        "attempts": job.attempts,
                    }
                    if job is not None
                    else None
                ),
                "latest_measurement": (
                    {
                        "metric_name": measurement_by_campaign[campaign.id].metric_name,
                        "observed_value": measurement_by_campaign[campaign.id].observed_value,
                        "incremental_value": measurement_by_campaign[campaign.id].incremental_value,
                        "source_mode": measurement_by_campaign[campaign.id].source_mode,
                        "measured_at": measurement_by_campaign[campaign.id].measured_at,
                    }
                    if campaign.id in measurement_by_campaign
                    else None
                ),
            }
        )
    return response


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
def create_campaign(
    payload: CampaignCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "campaign_manager")),
) -> Campaign:
    target_customer_id = None
    target_segment = payload.target_segment
    if payload.nba_decision_id is not None:
        decision = db.get(NBADecision, payload.nba_decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="NBA recommendation not found")
        if decision.status not in {"proposed", "overridden"}:
            raise HTTPException(status_code=409, detail="NBA recommendation is not available for campaign use")
        target_customer = (
            db.query(Customer)
            .filter(Customer.id == decision.customer_id, Customer.is_demo.is_(False))
            .first()
        )
        if target_customer is None:
            raise HTTPException(status_code=409, detail="NBA customer is missing or marked as demo data")
        target_customer_id = target_customer.id
        target_segment = target_customer.segment
    campaign = Campaign(
        name=payload.name,
        target_segment=target_segment,
        channel=payload.channel,
        ab_test_ratio=payload.ab_test_ratio,
        message_draft=payload.message_draft,
        correlation_id=request.state.correlation_id,
        status="Draft",
        created_by=actor.id,
        nba_decision_id=payload.nba_decision_id,
        target_customer_id=target_customer_id,
    )
    db.add(campaign)
    db.flush()
    record_audit_event(
        db,
        correlation_id=campaign.correlation_id or request.state.correlation_id,
        event_type="campaign.created",
        actor_id=actor.id,
        entity_type="campaign",
        entity_id=campaign.id,
        details={
            "status": campaign.status,
            "nba_decision_id": campaign.nba_decision_id,
            "target_customer_id": campaign.target_customer_id,
        },
    )
    db.commit()
    db.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/request-approval", response_model=CampaignResponse)
def request_campaign_approval(
    campaign_id: DBId,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "campaign_manager")),
) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "Draft":
        raise HTTPException(
            status_code=409, detail="Only draft campaigns can be submitted"
        )
    if not campaign.message_draft:
        raise HTTPException(
            status_code=409, detail="A message draft is required for approval"
        )
    campaign.status = "PendingApproval"
    record_audit_event(
        db,
        correlation_id=campaign.correlation_id or request.state.correlation_id,
        event_type="campaign.submitted_for_approval",
        actor_id=actor.id,
        entity_type="campaign",
        entity_id=campaign.id,
        details={"message_draft": campaign.message_draft},
    )
    db.commit()
    db.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/approve", response_model=CampaignResponse)
def approve_campaign(
    campaign_id: DBId,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "campaign_manager")),
) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "PendingApproval":
        raise HTTPException(status_code=409, detail="Campaign is not awaiting approval")
    campaign.status = "Approved"
    campaign.approved_by = actor.id
    campaign.approved_at = datetime.now(timezone.utc)
    record_audit_event(
        db,
        correlation_id=campaign.correlation_id or request.state.correlation_id,
        event_type="campaign.approved",
        actor_id=actor.id,
        entity_type="campaign",
        entity_id=campaign.id,
        details={
            "message_draft": campaign.message_draft,
            "nba_decision_id": campaign.nba_decision_id,
        },
    )
    db.commit()
    db.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/launch", response_model=dict)
def launch_campaign(
    campaign_id: DBId,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "campaign_manager")),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "Approved":
        raise HTTPException(
            status_code=409, detail="Campaign requires human approval before launch"
        )

    campaign.status = "Active"

    # Enqueue a batch job for batch worker orchestration
    job = BatchJob(
        kind="campaign_execution",
        payload={
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "target_segment": campaign.target_segment,
            "target_customer_id": campaign.target_customer_id,
            "channel": campaign.channel,
            "ab_test_ratio": campaign.ab_test_ratio,
            "channel_simulator": True,  # Strictly channel simulator compliant with NFR-10
            "correlation_id": campaign.correlation_id or request.state.correlation_id,
        },
        max_attempts=3,
        created_by=actor.id,
    )
    db.add(job)
    db.flush()
    campaign.execution_job_id = job.id
    record_audit_event(
        db,
        correlation_id=campaign.correlation_id or request.state.correlation_id,
        event_type="campaign.launched",
        actor_id=actor.id,
        entity_type="campaign",
        entity_id=campaign.id,
        details={"batch_job_id": job.id, "channel_simulator": True},
    )
    db.commit()
    db.refresh(job)

    return {
        "message": f"Simulasi kampanye '{campaign.name}' masuk antrean worker.",
        "campaign_id": campaign.id,
        "status": campaign.status,
        "batch_job_id": job.id,
    }
