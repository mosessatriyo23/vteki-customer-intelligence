from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.requests import Request

from api.audit import record_audit_event
from api.database import get_db
from api.models import BatchJob, User
from api.security import require_roles
from api.validation import DBId

router = APIRouter(prefix="/jobs", tags=["batch jobs"])
JobKind = str


class JobCreate(BaseModel):
    kind: JobKind = Field(min_length=1, max_length=64, pattern=r"^[^\x00]*$")
    payload: dict = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10, strict=True)
    idempotency_key: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[^\x00]*$"
    )

    @field_validator("max_attempts", mode="before")
    @classmethod
    def normalize_max_attempts(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("max_attempts must be an integer, not a boolean")
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value


class JobResponse(BaseModel):
    id: int
    kind: str
    status: str
    payload: dict
    result: dict | None
    attempts: int
    max_attempts: int
    last_error: str | None
    idempotency_key: str | None
    created_at: datetime


@router.get("", response_model=list[JobResponse])
def list_jobs(
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "operator", "analyst", "campaign_manager")
    ),
) -> list[BatchJob]:
    return db.query(BatchJob).order_by(BatchJob.id.desc()).limit(100).all()


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "operator", "campaign_manager")),
) -> BatchJob:
    if payload.idempotency_key:
        existing = (
            db.query(BatchJob)
            .filter(BatchJob.idempotency_key == payload.idempotency_key)
            .first()
        )
        if existing is not None:
            if (
                existing.kind != payload.kind
                or existing.payload != payload.payload
                or existing.max_attempts != payload.max_attempts
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key already exists with different job content",
                )
            return existing

    job = BatchJob(
        kind=payload.kind,
        payload=payload.payload,
        max_attempts=payload.max_attempts,
        idempotency_key=payload.idempotency_key,
        created_by=actor.id,
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        if not payload.idempotency_key:
            raise
        existing = (
            db.query(BatchJob)
            .filter(BatchJob.idempotency_key == payload.idempotency_key)
            .first()
        )
        if existing is None:
            raise
        if (
            existing.kind != payload.kind
            or existing.payload != payload.payload
            or existing.max_attempts != payload.max_attempts
        ):
            raise HTTPException(
                status_code=409,
                detail="Idempotency key already exists with different job content",
            )
        return existing
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: DBId,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "operator", "campaign_manager")),
) -> BatchJob:
    job = db.get(BatchJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "cancel_requested":
        return job
    if job.status == "queued":
        job.status = "cancelled"
        event_type = "batch.cancelled"
    elif job.status == "running":
        job.status = "cancel_requested"
        event_type = "batch.cancel_requested"
    else:
        raise HTTPException(
            status_code=409,
            detail=f"Job cannot be cancelled from status {job.status}",
        )

    record_audit_event(
        db,
        correlation_id=request.state.correlation_id,
        event_type=event_type,
        actor_id=actor.id,
        entity_type="batch_job",
        entity_id=job.id,
        details={
            "kind": job.kind,
            "previous_status": (
                "queued" if event_type == "batch.cancelled" else "running"
            ),
        },
    )
    db.commit()
    db.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: DBId,
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "operator", "analyst", "campaign_manager")
    ),
) -> BatchJob:
    job = db.get(BatchJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
