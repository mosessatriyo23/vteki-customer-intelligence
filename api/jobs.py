from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import BatchJob, User
from api.security import require_roles

router = APIRouter(prefix="/jobs", tags=["batch jobs"])
JobKind = str


class JobCreate(BaseModel):
    kind: JobKind
    payload: dict = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)


class JobResponse(BaseModel):
    id: int
    kind: str
    status: str
    payload: dict
    result: dict | None
    attempts: int
    max_attempts: int
    last_error: str | None
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
    job = BatchJob(
        kind=payload.kind,
        payload=payload.payload,
        max_attempts=payload.max_attempts,
        created_by=actor.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles("admin", "operator", "analyst", "campaign_manager")
    ),
) -> BatchJob:
    job = db.get(BatchJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
