"""As-of reads for visit and membership source-event history."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import BusinessEventHistory, IngestionBatch


def get_business_events_as_of(
    session: Session,
    *,
    source_customer_ref: str,
    effective_at: datetime,
    known_at: datetime,
    event_types: set[str] | None = None,
) -> list[BusinessEventHistory]:
    """Return published source events visible at both requested cutoffs."""
    _require_aware(effective_at, "effective_at")
    _require_aware(known_at, "known_at")
    if not source_customer_ref:
        raise ValueError("source_customer_ref is required")

    statement = (
        select(BusinessEventHistory)
        .join(
            IngestionBatch,
            IngestionBatch.batch_id == BusinessEventHistory.source_batch_id,
        )
        .where(
            BusinessEventHistory.source_customer_ref == source_customer_ref,
            BusinessEventHistory.occurred_at <= effective_at,
            BusinessEventHistory.available_at <= known_at,
            IngestionBatch.status == "PUBLISHED",
        )
    )
    if event_types is not None:
        if not event_types:
            return []
        statement = statement.where(BusinessEventHistory.event_type.in_(event_types))

    statement = statement.order_by(
        BusinessEventHistory.occurred_at,
        BusinessEventHistory.available_at,
        BusinessEventHistory.recorded_at,
        BusinessEventHistory.event_id,
    )
    return list(session.scalars(statement).all())


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
