"""Persistence adapter for Customer360 profile snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import ProfileSnapshot


def save_profile_snapshots(
    profiles: list[dict[str, Any]],
    batch_id: str,
    registry_version: str,
    session: Session,
) -> int:
    """Persists Customer 360 profile snapshots into persistent storage.

    Enforces unique constraint:
    (golden_customer_id, cutoff_at, identity_registry_version, source_batch_id)
    """
    now = datetime.now(timezone.utc)
    persisted_count = 0

    for p in profiles:
        cutoff_dt = datetime.fromisoformat(p["cutoff_at"])
        first_join = (
            datetime.fromisoformat(p["first_join_date"]).date()
            if isinstance(p["first_join_date"], str)
            else p["first_join_date"]
        )
        last_tx = (
            datetime.fromisoformat(p["last_transaction_at"])
            if p.get("last_transaction_at")
            else None
        )

        stmt = select(ProfileSnapshot).where(
            ProfileSnapshot.golden_customer_id == p["golden_customer_id"],
            ProfileSnapshot.cutoff_at == cutoff_dt,
            ProfileSnapshot.identity_registry_version == registry_version,
            ProfileSnapshot.source_batch_id == batch_id,
        )
        existing = session.scalars(stmt).first()

        if existing:
            existing.generated_at = now
            existing.identity_status = p["identity_status"]
            existing.source_identity_count = int(p["source_identity_count"])
            existing.first_join_date = first_join
            existing.transaction_count = int(p["transaction_count"])
            existing.retained_revenue = int(p["retained_revenue"])
            existing.last_transaction_at = last_tx
            existing.visit_count = int(p["visit_count"])
            existing.renewal_count = int(p["renewal_count"])
        else:
            snapshot = ProfileSnapshot(
                golden_customer_id=p["golden_customer_id"],
                cutoff_at=cutoff_dt,
                generated_at=now,
                identity_registry_version=registry_version,
                source_batch_id=batch_id,
                identity_status=p["identity_status"],
                source_identity_count=int(p["source_identity_count"]),
                first_join_date=first_join,
                transaction_count=int(p["transaction_count"]),
                retained_revenue=int(p["retained_revenue"]),
                last_transaction_at=last_tx,
                visit_count=int(p["visit_count"]),
                renewal_count=int(p["renewal_count"]),
            )
            session.add(snapshot)
        persisted_count += 1

    session.commit()
    return persisted_count
 