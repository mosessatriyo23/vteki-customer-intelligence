from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import BatchJob, Campaign, User
from api.security import require_roles

router = APIRouter(prefix="/campaigns", tags=["campaign builder"])


class CampaignResponse(BaseModel):
    id: int
    name: str
    target_segment: str
    channel: str
    ab_test_ratio: int
    status: str
    message_draft: str | None
    approved_by: int | None
    approved_at: datetime | None
    correlation_id: str | None
    created_by: int | None
    created_at: datetime


class CampaignCreate(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    target_segment: str = Field(min_length=2, max_length=64)
    channel: str = Field(min_length=2, max_length=32)  # email_sim, sms_sim, push_sim
    ab_test_ratio: int = Field(default=50, ge=0, le=100)
    message_draft: str | None = Field(default=None, max_length=2000)


@router.get("", response_model=list[CampaignResponse])
def list_campaigns(
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "analyst", "campaign_manager", "operator")
    ),
) -> list[Campaign]:
    return db.query(Campaign).order_by(Campaign.id.desc()).all()


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
def create_campaign(
    payload: CampaignCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "campaign_manager")),
) -> Campaign:
    campaign = Campaign(
        name=payload.name,
        target_segment=payload.target_segment,
        channel=payload.channel,
        ab_test_ratio=payload.ab_test_ratio,
        message_draft=payload.message_draft,
        correlation_id=request.state.correlation_id,
        status="Draft",
        created_by=actor.id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    record_audit_event(
        db,
        correlation_id=campaign.correlation_id or request.state.correlation_id,
        event_type="campaign.created",
        actor_id=actor.id,
        entity_type="campaign",
        entity_id=campaign.id,
        details={"status": campaign.status},
    )
    db.commit()
    return campaign


@router.post("/{campaign_id}/request-approval", response_model=CampaignResponse)
def request_campaign_approval(
    campaign_id: int,
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
            status_code=422, detail="A message draft is required for approval"
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
    campaign_id: int,
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
        details={"message_draft": campaign.message_draft},
    )
    db.commit()
    db.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/launch", response_model=dict)
def launch_campaign(
    campaign_id: int,
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
        "message": f"Campaign '{campaign.name}' successfully launched!",
        "campaign_id": campaign.id,
        "status": campaign.status,
        "batch_job_id": job.id,
    }
