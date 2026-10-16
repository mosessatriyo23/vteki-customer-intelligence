"""Read-only versioned Golden Customer serving API (not core demo customers)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import (
    AuditEvent,
    ProfileSnapshot,
    ReviewAuditLog,
    RFMLifecycleSnapshot,
    SourceIdentityMapping,
    User,
)
from api.security import require_roles

router = APIRouter(prefix="/customers/golden", tags=["golden customer 360"])
READ_ROLES = ("admin", "analyst", "campaign_manager", "operator")


class GoldenCustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    golden_customer_id: str
    cutoff_at: datetime
    generated_at: datetime
    identity_registry_version: str
    rule_version: str
    source_batch_id: str
    identity_status: str
    source_identity_count: int
    transaction_count: int
    retained_revenue: int
    visit_count: int
    renewal_count: int
    lifecycle: str | None = None
    rfm_code: str | None = None


def _serialize(db: Session, profile: ProfileSnapshot) -> GoldenCustomerResponse:
    # RFM may use a different rule_version: join by Golden, cutoff, registry,
    # and batch. Never associate an unrelated model version or source batch.
    segment = db.scalars(
        select(RFMLifecycleSnapshot)
        .where(
            RFMLifecycleSnapshot.golden_customer_id == profile.golden_customer_id,
            RFMLifecycleSnapshot.cutoff_at == profile.cutoff_at,
            RFMLifecycleSnapshot.identity_registry_version
            == profile.identity_registry_version,
            RFMLifecycleSnapshot.source_batch_id == profile.source_batch_id,
        )
        .order_by(
            RFMLifecycleSnapshot.generated_at.desc(),
            RFMLifecycleSnapshot.id.desc(),
        )
        .limit(1)
    ).first()
    return GoldenCustomerResponse(
        golden_customer_id=profile.golden_customer_id,
        cutoff_at=profile.cutoff_at,
        generated_at=profile.generated_at,
        identity_registry_version=profile.identity_registry_version,
        rule_version=profile.rule_version,
        source_batch_id=profile.source_batch_id,
        identity_status=profile.identity_status,
        source_identity_count=profile.source_identity_count,
        transaction_count=profile.transaction_count,
        retained_revenue=profile.retained_revenue,
        visit_count=profile.visit_count,
        renewal_count=profile.renewal_count,
        lifecycle=segment.lifecycle if segment else None,
        rfm_code=segment.rfm_code if segment else None,
    )


@router.get("", response_model=list[GoldenCustomerResponse])
def list_golden_customers(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[GoldenCustomerResponse]:
    # Window function produces exactly one most recent snapshot per Golden ID.
    ranked = select(
        ProfileSnapshot.id.label("snapshot_id"),
        func.row_number()
        .over(
            partition_by=ProfileSnapshot.golden_customer_id,
            order_by=(
                ProfileSnapshot.cutoff_at.desc(),
                ProfileSnapshot.generated_at.desc(),
                ProfileSnapshot.id.desc(),
            ),
        )
        .label("snapshot_rank"),
    ).subquery()
    profiles = db.scalars(
        select(ProfileSnapshot)
        .join(ranked, ranked.c.snapshot_id == ProfileSnapshot.id)
        .where(ranked.c.snapshot_rank == 1)
        .order_by(ProfileSnapshot.cutoff_at.desc(), ProfileSnapshot.golden_customer_id)
        .limit(limit)
    ).all()
    return [_serialize(db, p) for p in profiles]


@router.get("/{golden_id}", response_model=GoldenCustomerResponse)
def get_golden_customer(
    golden_id: str = Path(min_length=1, max_length=36, pattern=r"^[A-Za-z0-9-]+$"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> GoldenCustomerResponse:
    profile = db.scalars(
        select(ProfileSnapshot)
        .where(ProfileSnapshot.golden_customer_id == golden_id)
        .order_by(
            ProfileSnapshot.cutoff_at.desc(),
            ProfileSnapshot.generated_at.desc(),
            ProfileSnapshot.id.desc(),
        )
        .limit(1)
    ).first()
    if profile is None:
        raise HTTPException(
            status_code=404, detail="Golden customer snapshot not found"
        )
    return _serialize(db, profile)


@router.get("/{golden_id}/provenance")
def golden_customer_provenance(
    golden_id: str = Path(min_length=1, max_length=36, pattern=r"^[A-Za-z0-9-]+$"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "analyst")),
) -> dict:
    profile = get_golden_customer(golden_id=golden_id, db=db, _=_)
    mappings = db.scalars(
        select(SourceIdentityMapping)
        .where(SourceIdentityMapping.golden_customer_id == golden_id)
        .order_by(SourceIdentityMapping.source_customer_id)
        .limit(limit)
    ).all()
    reviews = db.scalars(
        select(ReviewAuditLog)
        .where(
            or_(
                ReviewAuditLog.previous_golden_id == golden_id,
                ReviewAuditLog.new_golden_id == golden_id,
            )
        )
        .order_by(ReviewAuditLog.performed_at.desc())
        .limit(limit)
    ).all()
    events = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == "golden_customer",
            AuditEvent.entity_id == golden_id,
        )
        .order_by(AuditEvent.occurred_at.desc())
        .limit(limit)
    ).all()
    return {
        "golden_customer_id": golden_id,
        "source": "customer360.profile_snapshots",
        "snapshot": profile,
        "mapping": [
            {
                "source_customer_id": m.source_customer_id,
                "source_batch_id": m.source_batch_id,
                "registry_version": m.registry_version,
                "assignment_type": m.assignment_type,
                "assigned_at": m.assigned_at,
            }
            for m in mappings
        ],
        "review_audit": [
            {
                "action": r.action,
                "actor_id": r.actor_id,
                "correlation_id": r.correlation_id,
                "performed_at": r.performed_at,
            }
            for r in reviews
        ],
        "audit": [
            {
                "event_type": e.event_type,
                "correlation_id": e.correlation_id,
                "occurred_at": e.occurred_at,
            }
            for e in events
        ],
    }
